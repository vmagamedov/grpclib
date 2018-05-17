import struct
import asyncio

import pytest
import async_timeout

from h2.config import H2Configuration
from h2.settings import SettingCodes
from h2.connection import H2Connection

from grpclib.const import Status
from grpclib.stream import CONTENT_TYPE
from grpclib.client import Stream, Handler
from grpclib.protocol import H2Protocol
from grpclib.metadata import Request, Deadline
from grpclib.exceptions import GRPCError

from stubs import TransportStub
from bombed_pb2 import SavoysRequest, SavoysReply


class ClientError(Exception):
    pass


class TimeoutDetected(Exception):
    pass


@pytest.fixture(name='broken_stream')
def _broken_stream():

    class BrokenChannel:
        def __connect__(self):
            raise IOError('Intentionally broken connection')

    request = Request('POST', 'http', '/foo/bar', authority='test.com')
    return Stream(BrokenChannel(), request, SavoysRequest, SavoysReply)


def encode_message(message):
    message_bin = message.SerializeToString()
    header = struct.pack('?', False) + struct.pack('>I', len(message_bin))
    return header + message_bin


class ServerStub:

    def __init__(self, protocol):
        self.connection = H2Connection(H2Configuration(client_side=False,
                                                       header_encoding='utf-8'))
        self._transport = TransportStub(self.connection)

        self._protocol = protocol
        self._protocol.connection_made(self._transport)

    def events(self):
        return self._transport.events()

    def flush(self):
        self._protocol.data_received(self.connection.data_to_send())


class ChannelStub:

    def __init__(self, protocol, *, connect_time=None):
        self.__protocol__ = protocol
        self.__connect_time = connect_time

    async def __connect__(self):
        if self.__connect_time is not None:
            await asyncio.sleep(self.__connect_time)
        return self.__protocol__


class Env:

    def __init__(self, *, loop, timeout=None, connect_time=None):
        config = H2Configuration(header_encoding='utf-8')
        self.protocol = H2Protocol(Handler(), config, loop=loop)

        self.channel = ChannelStub(self.protocol, connect_time=connect_time)

        deadline = timeout and Deadline.from_timeout(timeout)
        self.request = Request('POST', 'http', '/foo/bar', authority='test.com',
                               deadline=deadline)

        self.stream = Stream(self.channel, self.request,
                             SavoysRequest, SavoysReply)
        self.server = ServerStub(self.protocol)


@pytest.fixture(name='env')
def env_fixture(loop, ):
    return Env(loop=loop)


@pytest.mark.asyncio
async def test_unary_unary(env):
    async with env.stream:
        await env.stream.send_message(SavoysRequest(kyler='bhatta'),
                                      end=True)

        events = env.server.events()
        stream_id = events[-1].stream_id

        env.server.connection.send_headers(
            stream_id,
            [(':status', '200'), ('content-type', CONTENT_TYPE)],
        )
        env.server.connection.send_data(
            stream_id,
            encode_message(SavoysReply(benito='giselle')),
        )
        env.server.connection.send_headers(
            stream_id,
            [('grpc-status', str(Status.OK.value))],
            end_stream=True,
        )
        env.server.flush()

        assert await env.stream.recv_message() == \
            SavoysReply(benito='giselle')


@pytest.mark.asyncio
async def test_no_request(env):
    async with env.stream:
        pass


@pytest.mark.asyncio
async def test_connection_error(broken_stream):
    with pytest.raises(IOError) as err:
        async with broken_stream:
            await broken_stream.send_request()
    err.match('Intentionally broken connection')


@pytest.mark.asyncio
async def test_method_unimplemented(env):
    with pytest.raises(GRPCError) as err:
        async with env.stream:
            await env.stream.send_message(SavoysRequest(kyler='bhatta'),
                                          end=True)

            events = env.server.events()
            stream_id = events[-1].stream_id

            env.server.connection.send_headers(
                stream_id,
                [(':status', '200'),
                 ('grpc-status', str(Status.UNIMPLEMENTED.value))],
            )
            env.server.connection.send_data(
                stream_id,
                encode_message(SavoysReply(benito='giselle')),
            )
            env.server.connection.send_headers(
                stream_id,
                [('grpc-status', str(Status.OK.value))],
                end_stream=True,
            )
            env.server.flush()

            assert await env.stream.recv_message()
    err.match('UNIMPLEMENTED')


@pytest.mark.asyncio
async def test_ctx_exit_with_error_and_closed_stream(env):
    with pytest.raises(ClientError):
        async with env.stream:
            await env.stream.send_request()
            events = env.server.events()
            env.server.connection.reset_stream(events[-1].stream_id)
            env.server.flush()
            raise ClientError()


@pytest.mark.asyncio
async def test_ctx_exit_with_error_and_closed_connection(env):
    with pytest.raises(ClientError):
        async with env.stream:
            await env.stream.send_request()
            env.server.connection.close_connection()
            env.server.flush()
            raise ClientError()


@pytest.mark.asyncio
async def test_outbound_streams_limit(env, loop):
    env.server.connection.update_settings({
        SettingCodes.MAX_CONCURRENT_STREAMS: 1,
    })
    env.server.flush()

    request = Request('POST', 'http', '/foo/bar', authority='test.com')

    async def worker1():
        s1 = Stream(env.channel, request, SavoysRequest, SavoysReply)
        async with s1:
            await s1.send_message(SavoysRequest(kyler='bhatta'), end=True)
            assert await s1.recv_message() == SavoysReply(benito='giselle')

    async def worker2():
        s2 = Stream(env.channel, request, SavoysRequest, SavoysReply)
        async with s2:
            await s2.send_message(SavoysRequest(kyler='bhatta'), end=True)
            assert await s2.recv_message() == SavoysReply(benito='giselle')

    def send_response(stream_id):
        env.server.connection.send_headers(
            stream_id,
            [(':status', '200'), ('content-type', CONTENT_TYPE)],
        )
        env.server.connection.send_data(
            stream_id,
            encode_message(SavoysReply(benito='giselle')),
        )
        env.server.connection.send_headers(
            stream_id,
            [('grpc-status', str(Status.OK.value))],
            end_stream=True,
        )
        env.server.flush()

    w1 = loop.create_task(worker1())
    w2 = loop.create_task(worker2())

    done, pending = await asyncio.wait([w1, w2], loop=loop, timeout=0.001)
    assert not done and pending == {w1, w2}

    send_response(1)
    await asyncio.wait_for(w1, 0.1, loop=loop)

    send_response(3)
    await asyncio.wait_for(w2, 0.1, loop=loop)


@pytest.mark.asyncio
async def test_deadline_waiting_send_request(loop):
    env = Env(loop=loop, timeout=0.01, connect_time=1)
    with pytest.raises(TimeoutDetected):
        with async_timeout.timeout(5) as safety_timeout:
            async with env.stream:
                try:
                    await env.stream.send_request()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise TimeoutDetected()


@pytest.mark.asyncio
async def test_deadline_waiting_send_message(loop):
    env = Env(loop=loop, timeout=0.01)
    with pytest.raises(TimeoutDetected):
        with async_timeout.timeout(5) as safety_timeout:
            async with env.stream:
                await env.stream.send_request()

                env.protocol.connection.write_ready.clear()
                try:
                    await env.stream.send_message(SavoysRequest(kyler='bhatta'),
                                                  end=True)
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise TimeoutDetected()


@pytest.mark.asyncio
async def test_deadline_waiting_recv_initial_metadata(loop):
    env = Env(loop=loop, timeout=0.01)
    with pytest.raises(TimeoutDetected):
        with async_timeout.timeout(5) as safety_timeout:
            async with env.stream:
                await env.stream.send_message(SavoysRequest(kyler='bhatta'),
                                              end=True)

                try:
                    await env.stream.recv_initial_metadata()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise TimeoutDetected()


@pytest.mark.asyncio
async def test_deadline_waiting_recv_message(loop):
    env = Env(loop=loop, timeout=0.01)
    with pytest.raises(TimeoutDetected):
        with async_timeout.timeout(5) as safety_timeout:
            async with env.stream:
                await env.stream.send_message(SavoysRequest(kyler='bhatta'),
                                              end=True)

                events = env.server.events()
                stream_id = events[-1].stream_id
                env.server.connection.send_headers(
                    stream_id,
                    [(':status', '200'), ('content-type', CONTENT_TYPE)],
                )
                env.server.flush()
                await env.stream.recv_initial_metadata()

                try:
                    await env.stream.recv_message()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise TimeoutDetected()


@pytest.mark.asyncio
async def test_deadline_waiting_recv_trailing_metadata(loop):
    env = Env(loop=loop, timeout=0.01)
    with pytest.raises(TimeoutDetected):
        with async_timeout.timeout(5) as safety_timeout:
            async with env.stream:
                await env.stream.send_message(SavoysRequest(kyler='bhatta'),
                                              end=True)

                events = env.server.events()
                stream_id = events[-1].stream_id

                env.server.connection.send_headers(
                    stream_id,
                    [(':status', '200'), ('content-type', CONTENT_TYPE)],
                )
                env.server.flush()
                await env.stream.recv_initial_metadata()

                env.server.connection.send_data(
                    stream_id,
                    encode_message(SavoysReply(benito='giselle')),
                )
                env.server.flush()
                await env.stream.recv_message()

                try:
                    await env.stream.recv_trailing_metadata()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise TimeoutDetected()


@pytest.mark.asyncio
async def test_deadline_waiting_cancel(loop):
    env = Env(loop=loop, timeout=0.01)
    with pytest.raises(TimeoutDetected):
        with async_timeout.timeout(5) as safety_timeout:
            async with env.stream:
                await env.stream.send_request()

                env.protocol.connection.write_ready.clear()
                try:
                    await env.stream.cancel()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise TimeoutDetected()
