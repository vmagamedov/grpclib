import struct
import asyncio

import pytest
import async_timeout

from faker import Faker
from h2.config import H2Configuration
from h2.settings import SettingCodes
from h2.connection import H2Connection

from grpclib.const import Status
from grpclib.client import Stream, Handler
from grpclib.protocol import H2Protocol
from grpclib.metadata import Request, Deadline
from grpclib.exceptions import GRPCError, StreamTerminatedError
from grpclib.encoding.proto import ProtoCodec

from stubs import TransportStub
from dummy_pb2 import DummyRequest, DummyReply


fake = Faker()


class ClientError(Exception):
    pass


class ErrorDetected(Exception):
    pass


@pytest.fixture(name='broken_stream')
def _broken_stream():

    class BrokenChannel:
        def __connect__(self):
            raise IOError('Intentionally broken connection')

    request = Request('POST', 'http', '/foo/bar',
                      content_type='application/grpc+proto',
                      authority='test.com')
    return Stream(BrokenChannel(), request, ProtoCodec(),
                  DummyRequest, DummyReply)


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
        self.request = Request('POST', 'http', '/foo/bar',
                               content_type='application/grpc+proto',
                               authority='test.com',
                               deadline=deadline)

        self.stream = Stream(self.channel, self.request, ProtoCodec(),
                             DummyRequest, DummyReply)
        self.server = ServerStub(self.protocol)


@pytest.fixture(name='env')
def env_fixture(loop, ):
    return Env(loop=loop)


@pytest.mark.asyncio
async def test_unary_unary(env):
    async with env.stream:
        await env.stream.send_message(DummyRequest(value='ping'), end=True)

        events = env.server.events()
        stream_id = events[-1].stream_id

        env.server.connection.send_headers(
            stream_id,
            [(':status', '200'),
             ('content-type', 'application/grpc+proto')],
        )
        env.server.connection.send_data(
            stream_id,
            encode_message(DummyReply(value='pong')),
        )
        env.server.connection.send_headers(
            stream_id,
            [('grpc-status', str(Status.OK.value))],
            end_stream=True,
        )
        env.server.flush()

        assert await env.stream.recv_message() == \
            DummyReply(value='pong')


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

    request = Request('POST', 'http', '/foo/bar',
                      content_type='application/grpc+proto',
                      authority='test.com')

    async def worker1():
        s1 = Stream(env.channel, request, ProtoCodec(),
                    DummyRequest, DummyReply)
        async with s1:
            await s1.send_message(DummyRequest(value='ping'), end=True)
            assert await s1.recv_message() == DummyReply(value='pong')

    async def worker2():
        s2 = Stream(env.channel, request, ProtoCodec(),
                    DummyRequest, DummyReply)
        async with s2:
            await s2.send_message(DummyRequest(value='ping'), end=True)
            assert await s2.recv_message() == DummyReply(value='pong')

    def send_response(stream_id):
        env.server.connection.send_headers(
            stream_id,
            [(':status', '200'),
             ('content-type', 'application/grpc+proto')],
        )
        env.server.connection.send_data(
            stream_id,
            encode_message(DummyReply(value='pong')),
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
async def test_deadline_during_send_request(loop):
    env = Env(loop=loop, timeout=0.01, connect_time=1)
    with pytest.raises(ErrorDetected):
        with async_timeout.timeout(5) as safety_timeout:
            async with env.stream:
                try:
                    await env.stream.send_request()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise ErrorDetected()


@pytest.mark.asyncio
async def test_deadline_during_send_message(loop):
    env = Env(loop=loop, timeout=0.01)
    with pytest.raises(ErrorDetected):
        with async_timeout.timeout(5) as safety_timeout:
            async with env.stream:
                await env.stream.send_request()

                env.protocol.connection.write_ready.clear()
                try:
                    await env.stream.send_message(DummyRequest(value='ping'),
                                                  end=True)
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise ErrorDetected()


@pytest.mark.asyncio
async def test_deadline_during_recv_initial_metadata(loop):
    env = Env(loop=loop, timeout=0.01)
    with pytest.raises(ErrorDetected):
        with async_timeout.timeout(5) as safety_timeout:
            async with env.stream:
                await env.stream.send_message(DummyRequest(value='ping'),
                                              end=True)

                try:
                    await env.stream.recv_initial_metadata()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise ErrorDetected()


@pytest.mark.asyncio
async def test_deadline_during_recv_message(loop):
    env = Env(loop=loop, timeout=0.01)
    with pytest.raises(ErrorDetected):
        with async_timeout.timeout(5) as safety_timeout:
            async with env.stream:
                await env.stream.send_message(DummyRequest(value='ping'),
                                              end=True)

                events = env.server.events()
                stream_id = events[-1].stream_id
                env.server.connection.send_headers(
                    stream_id,
                    [(':status', '200'),
                     ('content-type', 'application/grpc+proto')],
                )
                env.server.flush()
                await env.stream.recv_initial_metadata()

                try:
                    await env.stream.recv_message()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise ErrorDetected()


@pytest.mark.asyncio
async def test_deadline_during_recv_trailing_metadata(loop):
    env = Env(loop=loop, timeout=0.01)
    with pytest.raises(ErrorDetected):
        with async_timeout.timeout(5) as safety_timeout:
            async with env.stream:
                await env.stream.send_message(DummyRequest(value='ping'),
                                              end=True)

                events = env.server.events()
                stream_id = events[-1].stream_id

                env.server.connection.send_headers(
                    stream_id,
                    [(':status', '200'),
                     ('content-type', 'application/grpc+proto')],
                )
                env.server.flush()
                await env.stream.recv_initial_metadata()

                env.server.connection.send_data(
                    stream_id,
                    encode_message(DummyReply(value='pong')),
                )
                env.server.flush()
                await env.stream.recv_message()

                try:
                    await env.stream.recv_trailing_metadata()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise ErrorDetected()


@pytest.mark.asyncio
async def test_deadline_during_cancel(loop):
    env = Env(loop=loop, timeout=0.01)
    with pytest.raises(ErrorDetected):
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
                        raise ErrorDetected()


@pytest.mark.asyncio
async def test_stream_reset_during_send_message(loop):
    env = Env(loop=loop)
    with pytest.raises(ErrorDetected):
        async with env.stream:
            await env.stream.send_request()

            events = env.server.events()
            stream_id = events[-1].stream_id
            env.protocol.connection.write_ready.clear()
            task = loop.create_task(
                env.stream.send_message(DummyRequest(value='ping'),
                                        end=True)
            )
            env.server.connection.reset_stream(stream_id)
            env.server.flush()

            try:
                await asyncio.wait_for(task, timeout=1, loop=loop)
            except StreamTerminatedError:
                raise ErrorDetected()


@pytest.mark.asyncio
async def test_connection_close_during_send_message(loop):
    env = Env(loop=loop)
    with pytest.raises(ErrorDetected):
        async with env.stream:
            await env.stream.send_request()

            env.protocol.connection.write_ready.clear()
            task = loop.create_task(
                env.stream.send_message(DummyRequest(value='ping'),
                                        end=True)
            )
            env.server.connection.close_connection()
            env.server.flush()

            try:
                await asyncio.wait_for(task, timeout=1, loop=loop)
            except StreamTerminatedError:
                raise ErrorDetected()


@pytest.mark.asyncio
async def test_unimplemented_error(loop):
    env = Env(loop=loop)
    with pytest.raises(ErrorDetected):
        async with env.stream:
            await env.stream.send_request()

            events = env.server.events()
            stream_id = events[-1].stream_id

            env.server.connection.send_headers(stream_id, [
                (':status', '200'),
                ('grpc-status', str(Status.UNIMPLEMENTED.value)),
            ], end_stream=True)
            env.server.flush()

            try:
                await env.stream.recv_initial_metadata()
            except GRPCError as exc:
                assert exc and exc.status == Status.UNIMPLEMENTED
                raise ErrorDetected()


@pytest.mark.asyncio
async def test_unimplemented_error_with_stream_reset(loop):
    env = Env(loop=loop)
    with pytest.raises(ErrorDetected):
        async with env.stream:
            await env.stream.send_request()

            events = env.server.events()
            stream_id = events[-1].stream_id

            env.server.connection.send_headers(stream_id, [
                (':status', '200'),
                ('grpc-status', str(Status.UNIMPLEMENTED.value)),
            ], end_stream=True)
            env.server.connection.reset_stream(stream_id)
            env.server.flush()

            try:
                await env.stream.recv_initial_metadata()
            except GRPCError as exc:
                assert exc and exc.status == Status.UNIMPLEMENTED
                raise ErrorDetected()


@pytest.mark.asyncio
@pytest.mark.parametrize('status, grpc_status', [
    ('401', Status.UNAUTHENTICATED),
    ('404', Status.UNIMPLEMENTED),
    ('429', Status.UNAVAILABLE),
    ('508', Status.UNKNOWN),
])
async def test_non_ok_status(loop, status, grpc_status):
    env = Env(loop=loop)
    with pytest.raises(ErrorDetected):
        async with env.stream:
            await env.stream.send_request()

            events = env.server.events()
            stream_id = events[-1].stream_id

            env.server.connection.send_headers(stream_id, [
                (':status', status),
            ], end_stream=True)
            env.server.connection.reset_stream(stream_id)
            env.server.flush()

            try:
                await env.stream.recv_initial_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == grpc_status
                assert exc.message == 'Received :status = {!r}'.format(status)
                raise ErrorDetected()


@pytest.mark.asyncio
async def test_missing_grpc_status(loop):
    env = Env(loop=loop)
    with pytest.raises(ErrorDetected):
        async with env.stream:
            await env.stream.send_request()

            events = env.server.events()
            stream_id = events[-1].stream_id

            env.server.connection.send_headers(stream_id, [
                (':status', '200'),
                ('content-type', 'application/grpc+proto'),
            ])
            env.server.connection.send_data(
                stream_id,
                encode_message(DummyReply(value='pong')),
            )
            env.server.connection.send_headers(stream_id, [
                ('foo', 'bar'),
            ], end_stream=True)
            env.server.flush()

            await env.stream.recv_initial_metadata()
            await env.stream.recv_message()
            try:
                await env.stream.recv_trailing_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == Status.UNKNOWN
                assert exc.message == 'Missing grpc-status header'
                raise ErrorDetected()


@pytest.mark.asyncio
@pytest.mark.parametrize('grpc_status', ['invalid_number', '-42'])
async def test_invalid_grpc_status_in_headers(loop, grpc_status):
    env = Env(loop=loop)
    with pytest.raises(ErrorDetected):
        async with env.stream:
            await env.stream.send_request()

            events = env.server.events()
            stream_id = events[-1].stream_id

            env.server.connection.send_headers(stream_id, [
                (':status', '200'),
                ('grpc-status', grpc_status),
            ], end_stream=True)
            env.server.flush()

            try:
                await env.stream.recv_initial_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == Status.UNKNOWN
                assert exc.message == ('Invalid grpc-status: {!r}'
                                       .format(grpc_status))
                raise ErrorDetected()


@pytest.mark.asyncio
@pytest.mark.parametrize('grpc_status', ['invalid_number', '-42'])
async def test_invalid_grpc_status_in_trailers(loop, grpc_status):
    env = Env(loop=loop)
    with pytest.raises(ErrorDetected):
        async with env.stream:
            await env.stream.send_request()

            events = env.server.events()
            stream_id = events[-1].stream_id

            env.server.connection.send_headers(stream_id, [
                (':status', '200'),
                ('content-type', 'application/grpc+proto'),
            ])
            env.server.connection.send_data(
                stream_id,
                encode_message(DummyReply(value='pong')),
            )
            env.server.connection.send_headers(stream_id, [
                ('grpc-status', grpc_status),
            ], end_stream=True)
            env.server.flush()

            await env.stream.recv_initial_metadata()
            await env.stream.recv_message()
            try:
                await env.stream.recv_trailing_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == Status.UNKNOWN
                assert exc.message == ('Invalid grpc-status: {!r}'
                                       .format(grpc_status))
                raise ErrorDetected()


@pytest.mark.asyncio
@pytest.mark.parametrize('grpc_message', [None, fake.pystr()])
async def test_non_ok_grpc_status_in_headers(loop, grpc_message):
    env = Env(loop=loop)
    with pytest.raises(ErrorDetected):
        async with env.stream:
            await env.stream.send_request()

            events = env.server.events()
            stream_id = events[-1].stream_id

            headers = [
                (':status', '200'),
                ('grpc-status', str(Status.DATA_LOSS.value)),
            ]
            if grpc_message is not None:
                headers.append(('grpc-message', grpc_message))
            env.server.connection.send_headers(stream_id, headers,
                                               end_stream=True)
            env.server.flush()

            try:
                await env.stream.recv_initial_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == Status.DATA_LOSS
                assert exc.message == grpc_message
                raise ErrorDetected()


@pytest.mark.asyncio
@pytest.mark.parametrize('grpc_message', [None, fake.pystr()])
async def test_non_ok_grpc_status_in_trailers(loop, grpc_message):
    env = Env(loop=loop)
    with pytest.raises(ErrorDetected):
        async with env.stream:
            await env.stream.send_request()

            events = env.server.events()
            stream_id = events[-1].stream_id

            env.server.connection.send_headers(stream_id, [
                (':status', '200'),
                ('content-type', 'application/grpc+proto'),
            ])
            env.server.connection.send_data(
                stream_id,
                encode_message(DummyReply(value='pong')),
            )
            headers = [
                ('grpc-status', str(Status.DATA_LOSS.value)),
            ]
            if grpc_message is not None:
                headers.append(('grpc-message', grpc_message))
            env.server.connection.send_headers(stream_id, headers,
                                               end_stream=True)
            env.server.flush()

            await env.stream.recv_initial_metadata()
            await env.stream.recv_message()
            try:
                await env.stream.recv_trailing_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == Status.DATA_LOSS
                assert exc.message == grpc_message
                raise ErrorDetected()


@pytest.mark.asyncio
async def test_missing_content_type(loop):
    env = Env(loop=loop)
    with pytest.raises(ErrorDetected):
        async with env.stream:
            await env.stream.send_request()

            events = env.server.events()
            stream_id = events[-1].stream_id

            env.server.connection.send_headers(stream_id, [
                (':status', '200'),
                ('grpc-status', str(Status.OK.value)),
            ])
            env.server.flush()

            try:
                await env.stream.recv_initial_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == Status.UNKNOWN
                assert exc.message == "Missing content-type header"
                raise ErrorDetected()


@pytest.mark.asyncio
async def test_invalid_content_type(loop):
    env = Env(loop=loop)
    with pytest.raises(ErrorDetected):
        async with env.stream:
            await env.stream.send_request()

            events = env.server.events()
            stream_id = events[-1].stream_id

            env.server.connection.send_headers(stream_id, [
                (':status', '200'),
                ('grpc-status', str(Status.OK.value)),
                ('content-type', 'text/invalid'),
            ])
            env.server.flush()

            try:
                await env.stream.recv_initial_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == Status.UNKNOWN
                assert exc.message == "Invalid content-type: 'text/invalid'"
                raise ErrorDetected()
