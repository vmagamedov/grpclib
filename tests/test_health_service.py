import asyncio

import pytest
import async_timeout

from grpclib.testing import channel_for
from grpclib.exceptions import GRPCError
from grpclib.health.check import ServiceCheck, ServiceStatus
from grpclib.health.service import Health
from grpclib.health.v1.health_pb2 import HealthCheckRequest, HealthCheckResponse
from grpclib.health.v1.health_grpc import HealthStub


class Check(ServiceCheck):
    __current_status__ = None

    async def check(self):
        return self.__current_status__


class Service:

    async def Foo(self, stream):
        raise NotImplementedError

    def __mapping__(self):
        return {
            '/{}/Method'.format(self.__class__.__name__): self.Foo,
        }


@pytest.mark.asyncio
async def test_check_unknown_service(loop):
    svc = Service()
    health = Health({svc: []})
    with channel_for([svc, health], loop=loop) as channel:
        stub = HealthStub(channel)

        with pytest.raises(GRPCError):
            await stub.Check(HealthCheckRequest())

        with pytest.raises(GRPCError):
            await stub.Check(HealthCheckRequest(service='Unknown'))


@pytest.mark.asyncio
async def test_check_zero_checks(loop):
    svc = Service()
    health = Health({svc: []})
    with channel_for([svc, health], loop=loop) as channel:
        stub = HealthStub(channel)
        response = await stub.Check(HealthCheckRequest(
            service=Service.__name__,
        ))
        assert response == HealthCheckResponse(
            status=HealthCheckResponse.SERVING,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize('v1, v2, status', [
    (None, None, HealthCheckResponse.UNKNOWN),
    (True, False, HealthCheckResponse.NOT_SERVING),
    (False, True, HealthCheckResponse.NOT_SERVING),
    (True, True, HealthCheckResponse.SERVING)
])
async def test_check_service_check(loop, v1, v2, status):
    svc = Service()
    c1 = Check(loop=loop, check_ttl=0)
    c2 = Check(loop=loop, check_ttl=0)
    health = Health({svc: [c1, c2]})
    with channel_for([svc, health], loop=loop) as channel:
        stub = HealthStub(channel)
        c1.__current_status__ = v1
        c2.__current_status__ = v2
        response = await stub.Check(HealthCheckRequest(
            service=Service.__name__,
        ))
        assert response == HealthCheckResponse(status=status)


@pytest.mark.asyncio
@pytest.mark.parametrize('v1, v2, status', [
    (None, None, HealthCheckResponse.UNKNOWN),
    (True, False, HealthCheckResponse.NOT_SERVING),
    (False, True, HealthCheckResponse.NOT_SERVING),
    (True, True, HealthCheckResponse.SERVING)
])
async def test_check_service_status(loop, v1, v2, status):
    svc = Service()
    s1 = ServiceStatus()
    s2 = ServiceStatus()
    health = Health({svc: [s1, s2]})
    with channel_for([svc, health], loop=loop) as channel:
        stub = HealthStub(channel)
        s1.set(v1)
        s2.set(v2)
        response = await stub.Check(HealthCheckRequest(
            service=Service.__name__,
        ))
        assert response == HealthCheckResponse(status=status)


@pytest.mark.asyncio
@pytest.mark.parametrize('request', [
    HealthCheckRequest(),
    HealthCheckRequest(service='Unknown'),
])
async def test_watch_unknown_service(loop, request):
    svc = Service()
    health = Health({svc: []})
    with channel_for([svc, health], loop=loop) as channel:
        stub = HealthStub(channel)
        async with stub.Watch.open() as stream:
            await stream.send_message(request, end=True)
            assert await stream.recv_message() == HealthCheckResponse(
                status=HealthCheckResponse.SERVICE_UNKNOWN,
            )
            try:
                with async_timeout.timeout(0.01):
                    assert not await stream.recv_message()
            except asyncio.TimeoutError:
                pass
            await stream.cancel()


@pytest.mark.asyncio
async def test_watch_zero_checks(loop):
    svc = Service()
    health = Health({svc: []})
    with channel_for([svc, health], loop=loop) as channel:
        stub = HealthStub(channel)
        async with stub.Watch.open() as stream:
            await stream.send_message(HealthCheckRequest(
                service=Service.__name__,
            ))
            response = await stream.recv_message()
            assert response == HealthCheckResponse(
                status=HealthCheckResponse.SERVING,
            )
            try:
                with async_timeout.timeout(0.01):
                    assert not await stream.recv_message()
            except asyncio.TimeoutError:
                pass
            await stream.cancel()


@pytest.mark.asyncio
async def test_watch_service_check(loop):
    svc = Service()
    c1 = Check(loop=loop, check_ttl=0.001)
    c2 = Check(loop=loop, check_ttl=0.001)
    health = Health({svc: [c1, c2]})
    with channel_for([svc, health], loop=loop) as channel:
        stub = HealthStub(channel)
        async with stub.Watch.open() as stream:
            await stream.send_message(HealthCheckRequest(
                service=Service.__name__,
            ))
            assert await stream.recv_message() == HealthCheckResponse(
                status=HealthCheckResponse.UNKNOWN,
            )

            # check that there are no unnecessary messages
            try:
                with async_timeout.timeout(0.01):
                    assert not await stream.recv_message()
            except asyncio.TimeoutError:
                pass

            c1.__current_status__ = True
            assert await stream.recv_message() == HealthCheckResponse(
                status=HealthCheckResponse.NOT_SERVING,
            )
            c2.__current_status__ = True
            assert await stream.recv_message() == HealthCheckResponse(
                status=HealthCheckResponse.SERVING,
            )
            c1.__current_status__ = False
            assert await stream.recv_message() == HealthCheckResponse(
                status=HealthCheckResponse.NOT_SERVING,
            )
            c1.__current_status__ = True
            assert await stream.recv_message() == HealthCheckResponse(
                status=HealthCheckResponse.SERVING,
            )
            await stream.cancel()


@pytest.mark.asyncio
async def test_watch_service_status(loop):
    svc = Service()
    s1 = ServiceStatus()
    s2 = ServiceStatus()
    health = Health({svc: [s1, s2]})
    with channel_for([svc, health], loop=loop) as channel:
        stub = HealthStub(channel)
        async with stub.Watch.open() as stream:
            await stream.send_message(HealthCheckRequest(
                service=Service.__name__,
            ))
            assert await stream.recv_message() == HealthCheckResponse(
                status=HealthCheckResponse.UNKNOWN,
            )
            s1.set(True)
            assert await stream.recv_message() == HealthCheckResponse(
                status=HealthCheckResponse.NOT_SERVING,
            )
            s2.set(True)
            assert await stream.recv_message() == HealthCheckResponse(
                status=HealthCheckResponse.SERVING,
            )
            s1.set(False)
            assert await stream.recv_message() == HealthCheckResponse(
                status=HealthCheckResponse.NOT_SERVING,
            )
            s1.set(True)
            assert await stream.recv_message() == HealthCheckResponse(
                status=HealthCheckResponse.SERVING,
            )

            # check that there are no unnecessary messages if status isn't
            # changed
            s1.set(True)
            try:
                with async_timeout.timeout(0.01):
                    assert not await stream.recv_message()
            except asyncio.TimeoutError:
                pass

            await stream.cancel()
