import pytest

from grpclib.const import Handler, Cardinality
from grpclib.interceptors import BaseInterceptor
from grpclib.server import request_handler
from grpclib.encoding.proto import ProtoCodec

from dummy_pb2 import DummyRequest, DummyReply
from test_server_stream import H2StreamStub


INTERCEPTOR_ON_REQUEST_EVENT = 'InterceptorOnRequest'
INTERCEPTOR_BEFORE_SEND_EVENT = 'InterceptorBeforeSend'
INTERCEPTOR_AFTER_SEND_EVENT = 'InterceptorAfterSend'


class OnRequestInterceptor(BaseInterceptor):
    async def on_request(self, stream, call_handler):
        stream._stream.__events__.append(INTERCEPTOR_ON_REQUEST_EVENT)
        await call_handler(stream)


class BeforeSendInterceptor(BaseInterceptor):
    async def before_send(self, stream, message):
        stream._stream.__events__.append(INTERCEPTOR_BEFORE_SEND_EVENT)
        return message


class AfterSendInterceptor(BaseInterceptor):
    async def after_send(self, stream, message):
        stream._stream.__events__.append(INTERCEPTOR_AFTER_SEND_EVENT)
        return message


@pytest.mark.asyncio
async def test_interceptor_is_called(loop):
    events = await _send_dummy_request(loop, [
        OnRequestInterceptor(),
        BeforeSendInterceptor(),
        AfterSendInterceptor(),
    ])

    assert events[0] == INTERCEPTOR_ON_REQUEST_EVENT

    assert INTERCEPTOR_BEFORE_SEND_EVENT in events
    assert INTERCEPTOR_AFTER_SEND_EVENT in events


async def _send_dummy_request(loop, interceptors):
    stream = H2StreamStub(loop=loop)
    headers = [
        (':method', 'POST'),
        (':path', '/package.Service/Method'),
        ('te', 'trailers'),
        ('content-type', 'application/grpc'),
    ]
    methods = {'/package.Service/Method': Handler(
        _dummy_handler,
        Cardinality.UNARY_UNARY,
        DummyRequest,
        DummyReply,
    )}

    await request_handler(
        methods, stream, headers, ProtoCodec(), interceptors=interceptors
    )
    return stream.__events__


async def _dummy_handler(stream):
    await stream.send_message(DummyReply(value='test'))
