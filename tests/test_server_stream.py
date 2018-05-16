import struct

from asyncio import Queue
from collections import namedtuple

import pytest

from h2.errors import ErrorCodes

from grpclib.const import Status, Cardinality
from grpclib.stream import CONTENT_TYPE, send_message
from grpclib.server import Stream, GRPCError
from grpclib.protocol import Connection, EventsProcessor
from grpclib.metadata import Metadata, Request
from grpclib.exceptions import ProtocolError

from stubs import TransportStub, DummyHandler
from bombed_pb2 import SavoysRequest, SavoysReply
from test_protocol import create_connections


SendHeaders = namedtuple('SendHeaders', 'headers, end_stream')
SendData = namedtuple('SendData', 'data, end_stream')
End = namedtuple('End', '')
Reset = namedtuple('Reset', 'error_code')


class ServerError(Exception):
    pass


class WriteError(Exception):
    pass


class H2StreamStub:

    def __init__(self, *, loop):
        self.__headers__ = Queue(loop=loop)
        self.__data__ = Queue(loop=loop)
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


@pytest.fixture(name='stub')
def _stub(loop):
    return H2StreamStub(loop=loop)


@pytest.fixture(name='stream')
def _stream(stub):
    return Stream(stub, Cardinality.UNARY_UNARY, SavoysRequest, SavoysReply,
                  metadata=Metadata([]))


@pytest.fixture(name='stream_streaming')
def _stream_streaming(stub):
    return Stream(stub, Cardinality.UNARY_STREAM, SavoysRequest, SavoysReply,
                  metadata=Metadata([]))


def encode_message(message):
    message_bin = message.SerializeToString()
    return (struct.pack('?', False)
            + struct.pack('>I', len(message_bin))
            + message_bin)


@pytest.mark.asyncio
async def test_no_response(stream, stub):
    async with stream:
        pass
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'),
             ('grpc-status', str(Status.UNKNOWN.value)),
             ('grpc-message', 'Empty response')],
            end_stream=True,
        ),
    ]


@pytest.mark.asyncio
async def test_send_initial_metadata_twice(stream):
    async with stream:
        await stream.send_initial_metadata()
        with pytest.raises(ProtocolError) as err:
            await stream.send_initial_metadata()
    err.match('Initial metadata was already sent')


@pytest.mark.asyncio
async def test_send_message_twice(stream):
    async with stream:
        await stream.send_message(SavoysReply(benito='aimee'))
        with pytest.raises(ProtocolError) as err:
            await stream.send_message(SavoysReply(benito='amaya'))
    err.match('Server should send exactly one message in response')


@pytest.mark.asyncio
async def test_send_message_twice_ok(stream_streaming, stub):
    async with stream_streaming:
        await stream_streaming.send_message(SavoysReply(benito='aimee'))
        await stream_streaming.send_message(SavoysReply(benito='amaya'))
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'), ('content-type', CONTENT_TYPE)],
            end_stream=False,
        ),
        SendData(
            encode_message(SavoysReply(benito='aimee')),
            end_stream=False,
        ),
        SendData(
            encode_message(SavoysReply(benito='amaya')),
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
async def test_send_trailing_metadata_and_empty_response(stream):
    async with stream:
        with pytest.raises(ProtocolError) as err:
            await stream.send_trailing_metadata()
    err.match('<Status\.OK: 0> requires non-empty response')


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
             ('grpc-status', str(Status.UNKNOWN.value)),
             ('grpc-message', 'Internal Server Error')],
            end_stream=True,
        ),
    ]


@pytest.mark.asyncio
async def test_error_after_send_initial_metadata(stream, stub):
    async with stream:
        await stream.send_initial_metadata()
        raise Exception()
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'), ('content-type', CONTENT_TYPE)],
            end_stream=False,
        ),
        SendHeaders(
            [('grpc-status', str(Status.UNKNOWN.value)),
             ('grpc-message', 'Internal Server Error')],
            end_stream=True,
        ),
    ]


@pytest.mark.asyncio
async def test_error_after_send_message(stream, stub):
    async with stream:
        await stream.send_message(SavoysReply(benito='aimee'))
        raise Exception()
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'), ('content-type', CONTENT_TYPE)],
            end_stream=False,
        ),
        SendData(
            encode_message(SavoysReply(benito='aimee')),
            end_stream=False,
        ),
        SendHeaders(
            [('grpc-status', str(Status.UNKNOWN.value)),
             ('grpc-message', 'Internal Server Error')],
            end_stream=True,
        ),
    ]


@pytest.mark.asyncio
async def test_error_after_send_trailing_metadata(stream, stub):
    async with stream:
        await stream.send_message(SavoysReply(benito='aimee'))
        await stream.send_trailing_metadata()
        raise Exception()
    assert stub.__events__ == [
        SendHeaders(
            [(':status', '200'), ('content-type', CONTENT_TYPE)],
            end_stream=False,
        ),
        SendData(
            encode_message(SavoysReply(benito='aimee')),
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
             ('grpc-status', str(Status.DEADLINE_EXCEEDED.value))],
            end_stream=True,
        ),
    ]


@pytest.mark.asyncio
async def test_exit_and_stream_was_closed(loop):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    to_server_transport = TransportStub(server_h2c)

    client_conn = Connection(client_h2c, to_server_transport, loop=loop)
    server_conn = Connection(server_h2c, to_client_transport, loop=loop)

    server_proc = EventsProcessor(DummyHandler(), server_conn)
    client_proc = EventsProcessor(DummyHandler(), client_conn)

    request = Request('POST', 'http', '/', authority='test.com')
    client_h2_stream = client_conn.create_stream()
    await client_h2_stream.send_request(request.to_headers(),
                                        _processor=client_proc)

    request = SavoysRequest(kyler='cloth')
    await send_message(client_h2_stream, request, SavoysRequest, end=True)
    to_server_transport.process(server_proc)

    server_h2_stream = server_proc.handler.stream
    request_metadata = Metadata.from_headers(server_proc.handler.headers)

    async with Stream(server_h2_stream, Cardinality.UNARY_UNARY,
                      SavoysRequest, SavoysReply,
                      metadata=request_metadata) as server_stream:
        await server_stream.recv_message()

        # simulating client closing stream
        await client_h2_stream.reset()
        to_server_transport.process(server_proc)


@pytest.mark.asyncio
async def test_exit_and_connection_was_closed(loop):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    to_server_transport = TransportStub(server_h2c)

    client_conn = Connection(client_h2c, to_server_transport, loop=loop)
    server_conn = Connection(server_h2c, to_client_transport, loop=loop)

    server_proc = EventsProcessor(DummyHandler(), server_conn)
    client_proc = EventsProcessor(DummyHandler(), client_conn)

    request = Request('POST', 'http', '/', authority='test.com')
    client_h2_stream = client_conn.create_stream()
    await client_h2_stream.send_request(request.to_headers(),
                                        _processor=client_proc)

    request = SavoysRequest(kyler='cloth')
    await send_message(client_h2_stream, request, SavoysRequest, end=True)
    to_server_transport.process(server_proc)

    server_h2_stream = server_proc.handler.stream
    request_metadata = Metadata.from_headers(server_proc.handler.headers)

    async with Stream(server_h2_stream, Cardinality.UNARY_UNARY,
                      SavoysRequest, SavoysReply,
                      metadata=request_metadata) as server_stream:
        await server_stream.recv_message()
        client_h2c.close_connection()
        to_server_transport.process(server_proc)

        raise ServerError()  # should be suppressed


@pytest.mark.asyncio
async def test_exit_and_connection_was_broken(loop):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    to_server_transport = TransportStub(server_h2c)

    client_conn = Connection(client_h2c, to_server_transport, loop=loop)
    server_conn = Connection(server_h2c, to_client_transport, loop=loop)

    server_proc = EventsProcessor(DummyHandler(), server_conn)
    client_proc = EventsProcessor(DummyHandler(), client_conn)

    request = Request('POST', 'http', '/', authority='test.com')
    client_h2_stream = client_conn.create_stream()
    await client_h2_stream.send_request(request.to_headers(),
                                        _processor=client_proc)

    request = SavoysRequest(kyler='cloth')
    await send_message(client_h2_stream, request, SavoysRequest, end=True)
    to_server_transport.process(server_proc)

    server_h2_stream = server_proc.handler.stream
    request_metadata = Metadata.from_headers(server_proc.handler.headers)

    with pytest.raises(WriteError):
        async with Stream(server_h2_stream, Cardinality.UNARY_UNARY,
                          SavoysRequest, SavoysReply,
                          metadata=request_metadata) as server_stream:
            await server_stream.recv_message()

            # simulate broken connection
            to_client_transport.__raise_on_write__(WriteError)
