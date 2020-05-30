import struct

from asyncio import Queue
from collections import namedtuple
from unittest.mock import Mock

import pytest

from h2.errors import ErrorCodes
from multidict import MultiDict

from grpclib.const import Status, Cardinality
from grpclib.events import _DispatchServerEvents
from grpclib.stream import send_message
from grpclib.server import Stream, GRPCError
from grpclib.protocol import Connection, EventsProcessor
from grpclib.metadata import decode_metadata
from grpclib.exceptions import ProtocolError
from grpclib.encoding.proto import ProtoCodec

from stubs import TransportStub, DummyHandler
from dummy_pb2 import DummyRequest, DummyReply
from test_protocol import create_connections, create_headers

SendHeaders = namedtuple('SendHeaders', 'headers, end_stream')
SendData = namedtuple('SendData', 'data, end_stream')
End = namedtuple('End', '')
Reset = namedtuple('Reset', 'error_code')


class ServerError(Exception):
    pass


class WriteError(Exception):
    pass


class H2TransportStub:

    def is_closing(self):
        return False


class H2StreamStub:
    _transport = H2TransportStub()

    def __init__(self):
        self.connection = Mock()
        self.connection.messages_sent = 0
        self.__headers__ = Queue()
        self.__data__ = Queue()
        self.__events__ = []

    async def recv_headers(self):
        return await self.__headers__.get()

    async def recv_data(self, size):
        data = await self.__data__.get()
        assert len(data) == size
        return data

    async def send_headers(self, headers, end_stream=False):
        self.__events__.append(SendHeaders(headers, end_stream))

    async def send_data(self, data, end_stream=False):
        self.__events__.append(SendData(data, end_stream))

    async def end(self):
        self.__events__.append(End())

    async def reset(self, error_code=ErrorCodes.NO_ERROR):
        self.__events__.append(Reset(error_code))

    @property
    def closable(self):
        return True

    def reset_nowait(self, error_code=ErrorCodes.NO_ERROR):
        self.__events__.append(Reset(error_code))


@pytest.fixture(name='stub')
def _stub():
    return H2StreamStub()


@pytest.fixture(name='stream')
def _stream(stub):
    stream = Stream(stub, '/svc/Method', Cardinality.UNARY_UNARY,
                    DummyRequest, DummyReply,
                    codec=ProtoCodec(), status_details_codec=None,
                    dispatch=_DispatchServerEvents())
    stream.metadata = MultiDict()
    return stream


@pytest.fixture(name='stream_streaming')
def _stream_streaming(stub):
    stream = Stream(stub, '/svc/Method', Cardinality.UNARY_STREAM,
                    DummyRequest, DummyReply,
                    codec=ProtoCodec(), status_details_codec=None,
                    dispatch=_DispatchServerEvents())
    stream.metadata = MultiDict()
    return stream


def encode_message(message):
    message_bin = message.SerializeToString()
    return (struct.pack('?', False)
            + struct.pack('>I', len(message_bin))
            + message_bin)


@pytest.mark.asyncio
async def test_send_custom_metadata(stream, stub):
    async with stream:
        await stream.send_initial_metadata(metadata={
            'foo': 'foo-value',
        })
        await stream.send_message(DummyReply(value='pong'))
        await stream.send_trailing_metadata(metadata={
            'bar': 'bar-value',
        })
    assert stub.__events__ == [
        SendHeaders(
            [
                (':status', '200'),
                ('content-type', 'application/grpc+proto'),
                ('foo', 'foo-value'),
            ],
            end_stream=False,
        ),
        SendData(
            encode_message(DummyReply(value='pong')),
            end_stream=False,
        ),
        SendHeaders(
            [
                ('grpc-status', str(Status.OK.value)),
                ('bar', 'bar-value'),
            ],
            end_stream=True,
        ),
    ]


@pytest.mark.asyncio
async def test_send_initial_metadata_twice(stream):
    async with stream:
        await stream.send_initial_metadata()
        with pytest.raises(ProtocolError) as err:
            await stream.send_initial_metadata()
        await stream.send_trailing_metadata(status=Status.UNKNOWN)
    err.match('Initial metadata was already sent')


@pytest.mark.asyncio
async def test_send_message_twice(stream):
    async with stream:
        await stream.send_message(DummyReply(value='pong1'))
        with pytest.raises(ProtocolError) as err:
            await stream.send_message(DummyReply(value='pong2'))
    err.match('Message was already sent')


@pytest.mark.asyncio
async def test_send_message_twice_ok(stream_streaming, stub):
    async with stream_streaming:
        await stream_streaming.send_message(DummyReply(value='pong1'))
        await stream_streaming.send_message(DummyReply(value='pong2'))
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'),
             ('content-type', 'application/grpc+proto')],
            end_stream=False,
        ),
        SendData(
            encode_message(DummyReply(value='pong1')),
            end_stream=False,
        ),
        SendData(
            encode_message(DummyReply(value='pong2')),
            end_stream=False,
        ),
        SendHeaders(
            [('grpc-status', str(Status.OK.value))],
            end_stream=True,
        ),
    ]


@pytest.mark.asyncio
async def test_send_trailing_metadata_twice(stream):
    async with stream:
        await stream.send_trailing_metadata(status=Status.UNKNOWN)
        with pytest.raises(ProtocolError) as err:
            await stream.send_trailing_metadata(status=Status.UNKNOWN)
    err.match('Trailing metadata was already sent')


@pytest.mark.asyncio
async def test_no_response(stream, stub):
    with pytest.raises(ProtocolError, match='requires a single message'):
        async with stream:
            pass
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'),
             ('content-type', 'application/grpc+proto'),
             ('grpc-status', str(Status.UNKNOWN.value)),
             ('grpc-message', 'Internal Server Error')],
            end_stream=True,
        ),
        Reset(ErrorCodes.NO_ERROR),
    ]


@pytest.mark.asyncio
async def test_no_messages_for_unary(stream):
    async with stream:
        with pytest.raises(ProtocolError) as err:
            await stream.send_trailing_metadata()
        raise err.value
    err.match('OK status requires a single message to be sent')


@pytest.mark.asyncio
async def test_no_messages_for_stream(stream_streaming, stub):
    async with stream_streaming:
        await stream_streaming.send_initial_metadata()
        await stream_streaming.send_trailing_metadata()
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'),
             ('content-type', 'application/grpc+proto')],
            end_stream=False,
        ),
        SendHeaders(
            [('grpc-status', str(Status.OK.value))],
            end_stream=True,
        ),
    ]


@pytest.mark.asyncio
async def test_successful_trailers_only_explicit(stream_streaming, stub):
    async with stream_streaming:
        await stream_streaming.send_trailing_metadata()
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'),
             ('content-type', 'application/grpc+proto'),
             ('grpc-status', str(Status.OK.value))],
            end_stream=True,
        ),
    ]


@pytest.mark.asyncio
async def test_successful_trailers_only_implicit(stream_streaming, stub):
    async with stream_streaming:
        pass
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'),
             ('content-type', 'application/grpc+proto'),
             ('grpc-status', str(Status.OK.value))],
            end_stream=True,
        ),
    ]


@pytest.mark.asyncio
async def test_cancel_twice(stream):
    async with stream:
        await stream.cancel()
        with pytest.raises(ProtocolError) as err:
            await stream.cancel()
    err.match('Stream was already cancelled')


@pytest.mark.asyncio
async def test_error_before_send_initial_metadata(stream, stub):
    async with stream:
        raise Exception()
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'),
             ('content-type', 'application/grpc+proto'),
             ('grpc-status', str(Status.UNKNOWN.value)),
             ('grpc-message', 'Internal Server Error')],
            end_stream=True,
        ),
        Reset(ErrorCodes.NO_ERROR),
    ]


@pytest.mark.asyncio
async def test_error_after_send_initial_metadata(stream, stub):
    async with stream:
        await stream.send_initial_metadata()
        raise Exception()
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'),
             ('content-type', 'application/grpc+proto')],
            end_stream=False,
        ),
        SendHeaders(
            [('grpc-status', str(Status.UNKNOWN.value)),
             ('grpc-message', 'Internal Server Error')],
            end_stream=True,
        ),
        Reset(ErrorCodes.NO_ERROR),
    ]


@pytest.mark.asyncio
async def test_error_after_send_message(stream, stub):
    async with stream:
        await stream.send_message(DummyReply(value='pong'))
        raise Exception()
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'),
             ('content-type', 'application/grpc+proto')],
            end_stream=False,
        ),
        SendData(
            encode_message(DummyReply(value='pong')),
            end_stream=False,
        ),
        SendHeaders(
            [('grpc-status', str(Status.UNKNOWN.value)),
             ('grpc-message', 'Internal Server Error')],
            end_stream=True,
        ),
        Reset(ErrorCodes.NO_ERROR),
    ]


@pytest.mark.asyncio
async def test_error_after_send_trailing_metadata(stream, stub):
    async with stream:
        await stream.send_message(DummyReply(value='pong'))
        await stream.send_trailing_metadata()
        raise Exception()
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'),
             ('content-type', 'application/grpc+proto')],
            end_stream=False,
        ),
        SendData(
            encode_message(DummyReply(value='pong')),
            end_stream=False,
        ),
        SendHeaders(
            [('grpc-status', str(Status.OK.value))],
            end_stream=True,
        ),
    ]


@pytest.mark.asyncio
async def test_grpc_error(stream, stub):
    async with stream:
        raise GRPCError(Status.DEADLINE_EXCEEDED)
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'),
             ('content-type', 'application/grpc+proto'),
             ('grpc-status', str(Status.DEADLINE_EXCEEDED.value))],
            end_stream=True,
        ),
        Reset(ErrorCodes.NO_ERROR),
    ]


def mk_stream(h2_stream, metadata):
    stream = Stream(h2_stream, '/svc/Method', Cardinality.UNARY_UNARY,
                    DummyRequest, DummyReply, codec=ProtoCodec(),
                    status_details_codec=None,
                    dispatch=_DispatchServerEvents())
    stream.metadata = metadata
    return stream


@pytest.mark.asyncio
async def test_exit_and_stream_was_closed(loop, config):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    to_server_transport = TransportStub(server_h2c)

    client_conn = Connection(client_h2c, to_server_transport, config=config)
    server_conn = Connection(server_h2c, to_client_transport, config=config)

    server_proc = EventsProcessor(DummyHandler(), server_conn)
    client_proc = EventsProcessor(DummyHandler(), client_conn)

    client_h2_stream = client_conn.create_stream()
    await client_h2_stream.send_request(create_headers(),
                                        _processor=client_proc)

    request = DummyRequest(value='ping')
    await send_message(client_h2_stream, ProtoCodec(), request, DummyRequest,
                       end=True)
    to_server_transport.process(server_proc)

    server_h2_stream = server_proc.handler.stream
    request_metadata = decode_metadata(server_proc.handler.headers)

    async with mk_stream(server_h2_stream, request_metadata) as server_stream:
        await server_stream.recv_message()

        # simulating client closing stream
        await client_h2_stream.reset()
        to_server_transport.process(server_proc)

        # we should fail here on this attempt to send something
        await server_stream.send_message(DummyReply(value='pong'))


@pytest.mark.asyncio
async def test_exit_and_connection_was_closed(loop, config):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    to_server_transport = TransportStub(server_h2c)

    client_conn = Connection(client_h2c, to_server_transport, config=config)
    server_conn = Connection(server_h2c, to_client_transport, config=config)

    server_proc = EventsProcessor(DummyHandler(), server_conn)
    client_proc = EventsProcessor(DummyHandler(), client_conn)

    client_h2_stream = client_conn.create_stream()
    await client_h2_stream.send_request(create_headers(),
                                        _processor=client_proc)

    request = DummyRequest(value='ping')
    await send_message(client_h2_stream, ProtoCodec(), request, DummyRequest,
                       end=True)
    to_server_transport.process(server_proc)

    server_h2_stream = server_proc.handler.stream
    request_metadata = decode_metadata(server_proc.handler.headers)

    async with mk_stream(server_h2_stream, request_metadata) as server_stream:
        await server_stream.recv_message()
        client_h2c.close_connection()
        to_server_transport.process(server_proc)

        raise ServerError()  # should be suppressed


@pytest.mark.asyncio
async def test_exit_and_connection_was_broken(loop, config):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    to_server_transport = TransportStub(server_h2c)

    client_conn = Connection(client_h2c, to_server_transport, config=config)
    server_conn = Connection(server_h2c, to_client_transport, config=config)

    server_proc = EventsProcessor(DummyHandler(), server_conn)
    client_proc = EventsProcessor(DummyHandler(), client_conn)

    client_h2_stream = client_conn.create_stream()
    await client_h2_stream.send_request(create_headers(),
                                        _processor=client_proc)

    request = DummyRequest(value='ping')
    await send_message(client_h2_stream, ProtoCodec(), request, DummyRequest,
                       end=True)
    to_server_transport.process(server_proc)

    server_h2_stream = server_proc.handler.stream
    request_metadata = decode_metadata(server_proc.handler.headers)

    with pytest.raises(WriteError):
        async with mk_stream(server_h2_stream,
                             request_metadata) as server_stream:
            server_stream.metadata = request_metadata
            await server_stream.recv_message()
            # simulate broken connection
            to_client_transport.__raise_on_write__(WriteError)


@pytest.mark.asyncio
async def test_send_trailing_metadata_on_closed_stream(loop, config):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    to_server_transport = TransportStub(server_h2c)

    client_conn = Connection(client_h2c, to_server_transport, config=config)
    server_conn = Connection(server_h2c, to_client_transport, config=config)

    server_proc = EventsProcessor(DummyHandler(), server_conn)
    client_proc = EventsProcessor(DummyHandler(), client_conn)

    client_h2_stream = client_conn.create_stream()
    await client_h2_stream.send_request(create_headers(),
                                        _processor=client_proc)

    request = DummyRequest(value='ping')
    await send_message(client_h2_stream, ProtoCodec(), request, DummyRequest,
                       end=True)
    to_server_transport.process(server_proc)

    server_h2_stream = server_proc.handler.stream
    request_metadata = decode_metadata(server_proc.handler.headers)

    send_trailing_metadata_done = False
    async with mk_stream(server_h2_stream, request_metadata) as server_stream:
        await server_stream.send_trailing_metadata(status=Status.UNKNOWN)
        send_trailing_metadata_done = True

    assert send_trailing_metadata_done
