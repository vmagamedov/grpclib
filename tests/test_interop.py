import pytest

from grpclib.server import Server
from grpclib.interop import InteropChannel

from dummy_pb2 import DummyRequest, DummyReply
from dummy_pb2_grpc import DummyServiceStub
from test_functional import DummyService


@pytest.fixture(name='svc')
def svc_fixture():
    return DummyService()


@pytest.fixture(name='server')
def server_fixture(loop, svc, addr):
    server = Server([svc], loop=loop)
    loop.run_until_complete(server.start(*addr))
    try:
        yield server
    finally:
        server.close()
        loop.run_until_complete(server.wait_closed())


@pytest.fixture(name='channel')
def channel_fixture(addr, loop, server):
    channel = InteropChannel(*addr, loop=loop)
    try:
        yield channel
    finally:
        channel.close()


@pytest.fixture(name='stub')
def stub_fixture(channel):
    return DummyServiceStub(channel)


@pytest.mark.asyncio
async def test_unary_unary(svc, stub):
    reply = await stub.UnaryUnary(DummyRequest(value='ping'))
    assert reply == DummyReply(value='pong')


@pytest.mark.asyncio
async def test_unary_stream(svc, stub):
    reply = await stub.UnaryStream(DummyRequest(value='ping'))
    assert reply == [
        DummyReply(value='pong1'),
        DummyReply(value='pong2'),
        DummyReply(value='pong3'),
    ]


@pytest.mark.asyncio
async def test_stream_unary(svc, stub):
    reply = await stub.StreamUnary([DummyRequest(value='ping')])
    assert reply == DummyReply(value='pong')


@pytest.mark.asyncio
async def test_stream_stream(svc, stub):
    reply = await stub.StreamStream([
        DummyRequest(value='ping1'),
        DummyRequest(value='ping2'),
        DummyRequest(value='ping3'),
    ])
    assert reply == [
        DummyReply(value='ping1'),
        DummyReply(value='ping2'),
        DummyReply(value='ping3'),
    ]
