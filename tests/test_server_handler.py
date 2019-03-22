import asyncio

import pytest

from h2.errors import ErrorCodes

from grpclib.const import Handler, Cardinality
from grpclib.events import _DispatchServerEvents
from grpclib.server import request_handler
from grpclib.protocol import Connection, EventsProcessor
from grpclib.encoding.proto import ProtoCodec

from stubs import TransportStub, DummyHandler
from dummy_pb2 import DummyRequest, DummyReply
from test_protocol import create_connections, create_headers
from test_server_stream import H2StreamStub, SendHeaders, Reset


def release_stream():
    pass


async def call_handler(mapping, stream, headers):
    await request_handler(mapping, stream, headers, ProtoCodec(),
                          _DispatchServerEvents(), release_stream)


@pytest.mark.asyncio
async def test_invalid_method(loop):
    stream = H2StreamStub(loop=loop)
    headers = [(':method', 'GET')]
    await call_handler({}, stream, headers)
    assert stream.__events__ == [
        SendHeaders(headers=[(':status', '405')], end_stream=True),
        Reset(ErrorCodes.NO_ERROR),
    ]


@pytest.mark.asyncio
async def test_missing_te_header(loop):
    stream = H2StreamStub(loop=loop)
    headers = [
        (':method', 'POST'),
        ('content-type', 'application/grpc'),
    ]
    await call_handler({}, stream, headers)
    assert stream.__events__ == [
        SendHeaders(headers=[
            (':status', '400'),
            ('grpc-status', '2'),  # UNKNOWN
            ('grpc-message', 'Required "te: trailers" header is missing'),
        ], end_stream=True),
        Reset(ErrorCodes.NO_ERROR),
    ]


@pytest.mark.asyncio
async def test_missing_content_type(loop):
    stream = H2StreamStub(loop=loop)
    headers = [
        (':method', 'POST'),
    ]
    await call_handler({}, stream, headers)
    assert stream.__events__ == [
        SendHeaders(headers=[
            (':status', '415'),
            ('grpc-status', '2'),  # UNKNOWN
            ('grpc-message', 'Missing content-type header'),
        ], end_stream=True),
        Reset(ErrorCodes.NO_ERROR),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize('content_type',
                         ['text/invalid', 'application/grpc+invalid'])
async def test_invalid_content_type(content_type, loop):
    stream = H2StreamStub(loop=loop)
    headers = [
        (':method', 'POST'),
        ('content-type', content_type),
    ]
    await call_handler({}, stream, headers)
    assert stream.__events__ == [
        SendHeaders(headers=[
            (':status', '415'),
            ('grpc-status', '2'),  # UNKNOWN
            ('grpc-message', 'Unacceptable content-type header'),
        ], end_stream=True),
        Reset(ErrorCodes.NO_ERROR),
    ]


@pytest.mark.asyncio
async def test_missing_method(loop):
    stream = H2StreamStub(loop=loop)
    headers = [
        (':method', 'POST'),
        (':path', '/missing.Service/MissingMethod'),
        ('te', 'trailers'),
        ('content-type', 'application/grpc'),
    ]
    await call_handler({}, stream, headers)
    assert stream.__events__ == [
        SendHeaders(headers=[
            (':status', '200'),
            ('grpc-status', '12'),  # UNIMPLEMENTED
            ('grpc-message', 'Method not found'),
        ], end_stream=True),
        Reset(ErrorCodes.NO_ERROR),
    ]


@pytest.mark.asyncio
async def test_invalid_grpc_timeout(loop):
    stream = H2StreamStub(loop=loop)
    headers = [
        (':method', 'POST'),
        (':path', '/package.Service/Method'),
        ('te', 'trailers'),
        ('content-type', 'application/grpc'),
        ('grpc-timeout', 'invalid'),
    ]
    methods = {'/package.Service/Method': object()}
    await call_handler(methods, stream, headers)
    assert stream.__events__ == [
        SendHeaders(headers=[
            (':status', '200'),
            ('grpc-status', '2'),  # UNKNOWN
            ('grpc-message', 'Invalid grpc-timeout header'),
        ], end_stream=True),
        Reset(ErrorCodes.NO_ERROR),
    ]


@pytest.mark.asyncio
async def test_deadline(loop):
    stream = H2StreamStub(loop=loop)
    headers = [
        (':method', 'POST'),
        (':path', '/package.Service/Method'),
        ('te', 'trailers'),
        ('content-type', 'application/grpc'),
        ('grpc-timeout', '10m'),
    ]

    async def _method(stream_):
        await asyncio.sleep(1)

    methods = {'/package.Service/Method': Handler(
        _method,
        Cardinality.UNARY_UNARY,
        DummyRequest,
        DummyReply,
    )}
    task = loop.create_task(
        call_handler(methods, stream, headers)
    )
    await asyncio.wait_for(task, 0.1, loop=loop)
    assert stream.__events__ == [
        SendHeaders(headers=[
            (':status', '200'),
            ('grpc-status', '4'),  # DEADLINE_EXCEEDED
        ], end_stream=True),
        Reset(ErrorCodes.NO_ERROR),
    ]


@pytest.mark.asyncio
async def test_client_reset(loop, caplog):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    to_server_transport = TransportStub(server_h2c)

    client_conn = Connection(client_h2c, to_server_transport, loop=loop)
    server_conn = Connection(server_h2c, to_client_transport, loop=loop)

    server_proc = EventsProcessor(DummyHandler(), server_conn)
    client_proc = EventsProcessor(DummyHandler(), client_conn)

    client_h2_stream = client_conn.create_stream()
    await client_h2_stream.send_request(
        create_headers(path='/package.Service/Method'),
        _processor=client_proc,
    )
    to_server_transport.process(server_proc)

    server_h2_stream = server_proc.handler.stream

    success = []

    async def _method(_):
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            success.append(True)
            raise

    methods = {'/package.Service/Method': Handler(
        _method,
        Cardinality.UNARY_UNARY,
        DummyRequest,
        DummyReply,
    )}
    task = loop.create_task(
        call_handler(methods, server_h2_stream, server_proc.handler.headers)
    )
    await asyncio.wait([task], timeout=0.001)
    await client_h2_stream.reset()
    to_server_transport.process(server_proc)
    await asyncio.wait_for(task, 0.1, loop=loop)
    assert success == [True]
    assert 'Request was cancelled' in caplog.text
