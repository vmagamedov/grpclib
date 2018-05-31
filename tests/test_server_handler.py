import asyncio

import pytest

from h2.errors import ErrorCodes

from grpclib.const import Handler, Cardinality
from grpclib.server import request_handler
from grpclib.encoding.proto import ProtoCodec

from dummy_pb2 import DummyRequest, DummyReply
from test_server_stream import H2StreamStub, SendHeaders, Reset


def release_stream():
    pass


@pytest.mark.asyncio
async def test_invalid_method(loop):
    stream = H2StreamStub(loop=loop)
    headers = [(':method', 'GET')]
    await request_handler({}, stream, headers, ProtoCodec(), release_stream)
    assert stream.__events__ == [
        SendHeaders(headers=[(':status', '405')], end_stream=True),
        Reset(ErrorCodes.NO_ERROR),
    ]


@pytest.mark.asyncio
async def test_missing_content_type(loop):
    stream = H2StreamStub(loop=loop)
    headers = [
        (':method', 'POST'),
    ]
    await request_handler({}, stream, headers, ProtoCodec(), release_stream)
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
    await request_handler({}, stream, headers, ProtoCodec(), release_stream)
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
        ('content-type', 'application/grpc'),
    ]
    await request_handler({}, stream, headers, ProtoCodec(), release_stream)
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
        ('content-type', 'application/grpc'),
        ('grpc-timeout', 'invalid'),
    ]
    methods = {'/package.Service/Method': object()}
    await request_handler(methods, stream, headers, ProtoCodec(),
                          release_stream)
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
        request_handler(methods, stream, headers, ProtoCodec(), release_stream)
    )
    await asyncio.wait_for(task, 0.1, loop=loop)
    assert stream.__events__ == [
        SendHeaders(headers=[
            (':status', '200'),
            ('grpc-status', '4'),  # DEADLINE_EXCEEDED
        ], end_stream=True),
        Reset(ErrorCodes.NO_ERROR),
    ]
