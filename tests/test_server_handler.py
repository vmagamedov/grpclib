import asyncio
import logging

import pytest

from h2.errors import ErrorCodes

from grpclib.const import Handler, Cardinality, Status
from grpclib.events import _DispatchServerEvents
from grpclib.server import request_handler
from grpclib.protocol import Connection, EventsProcessor
from grpclib.exceptions import StreamTerminatedError
from grpclib.encoding.proto import ProtoCodec

from stubs import TransportStub, DummyHandler
from dummy_pb2 import DummyRequest, DummyReply
from test_protocol import create_connections, create_headers
from test_server_stream import H2StreamStub, SendHeaders, Reset


def release_stream():
    pass


async def call_handler(mapping, stream, headers):
    await request_handler(mapping, stream, headers, ProtoCodec(), None,
                          _DispatchServerEvents(), release_stream)


@pytest.mark.asyncio
async def test_invalid_method():
    stream = H2StreamStub()
    headers = [(':method', 'GET')]
    await call_handler({}, stream, headers)
    assert stream.__events__ == [
        SendHeaders(headers=[(':status', '405')], end_stream=True),
        Reset(ErrorCodes.NO_ERROR),
    ]


@pytest.mark.asyncio
async def test_missing_te_header():
    stream = H2StreamStub()
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
async def test_missing_content_type():
    stream = H2StreamStub()
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
async def test_invalid_content_type(content_type):
    stream = H2StreamStub()
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
async def test_missing_method():
    stream = H2StreamStub()
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
async def test_invalid_grpc_timeout():
    stream = H2StreamStub()
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


async def _slow_handler(_):
    await asyncio.sleep(1)


async def _broken_handler(_):
    """Unable to properly handle cancel"""
    try:
        await asyncio.sleep(1)
    except asyncio.CancelledError:
        raise Exception('This was unexpected')


@pytest.mark.asyncio
@pytest.mark.parametrize('handler, level, msg, exc_type, exc_text', [
    (
        _slow_handler, 'INFO', 'Deadline exceeded',
        None, None,
    ),
    (
        _broken_handler, 'ERROR', 'Failed to handle cancellation',
        asyncio.TimeoutError, 'This was unexpected',
    ),
])
async def test_deadline(
    loop, caplog, handler, level, msg, exc_type, exc_text
):
    caplog.set_level(logging.INFO)
    stream = H2StreamStub()
    headers = [
        (':method', 'POST'),
        (':path', '/package.Service/Method'),
        ('te', 'trailers'),
        ('content-type', 'application/grpc'),
        ('grpc-timeout', '50m'),
    ]
    methods = {'/package.Service/Method': Handler(
        handler,
        Cardinality.UNARY_UNARY,
        DummyRequest,
        DummyReply,
    )}
    task = loop.create_task(
        call_handler(methods, stream, headers)
    )
    await asyncio.wait_for(task, 0.1)  # should be bigger than grpc-timeout
    assert stream.__events__ == [
        SendHeaders(headers=[
            (':status', '200'),
            ('content-type', 'application/grpc+proto'),
            ('grpc-status', str(Status.DEADLINE_EXCEEDED.value)),
        ], end_stream=True),
        Reset(ErrorCodes.NO_ERROR),
    ]

    record, = caplog.records
    assert record.name == 'grpclib.server'
    assert record.levelname == level
    assert msg in record.getMessage()
    if exc_type is not None:
        assert record.exc_info[0] is exc_type
    if exc_text is not None:
        assert exc_text in record.exc_text


@pytest.mark.asyncio
@pytest.mark.parametrize('handler, level, msg, exc_type, exc_text', [
    (
        _slow_handler, 'INFO',
        'Request was cancelled: Stream reset by remote party',
        None, None,
    ),
    (
        _broken_handler, 'ERROR',
        'Failed to handle cancellation',
        StreamTerminatedError, 'This was unexpected',
    ),
])
async def test_client_reset(
    loop, caplog, handler, level, msg, exc_type, exc_text, config,
):
    caplog.set_level(logging.INFO)
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    to_server_transport = TransportStub(server_h2c)

    client_conn = Connection(client_h2c, to_server_transport, config=config)
    server_conn = Connection(server_h2c, to_client_transport, config=config)

    server_proc = EventsProcessor(DummyHandler(), server_conn)
    client_proc = EventsProcessor(DummyHandler(), client_conn)

    client_h2_stream = client_conn.create_stream()
    await client_h2_stream.send_request(
        create_headers(path='/package.Service/Method'),
        _processor=client_proc,
    )
    to_server_transport.process(server_proc)

    server_h2_stream = server_proc.handler.stream

    methods = {'/package.Service/Method': Handler(
        handler,
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
    await asyncio.wait_for(task, 0.1)

    record, = caplog.records
    assert record.name == 'grpclib.server'
    assert record.levelname == level
    assert msg in record.getMessage()
    if exc_type is not None:
        assert record.exc_info[0] is exc_type
    if exc_text is not None:
        assert exc_text in record.exc_text
