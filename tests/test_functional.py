import os
import socket
import tempfile

import pytest

from grpclib.client import Channel
from grpclib.server import Server

from dummy_pb2 import DummyRequest, DummyReply
from dummy_grpc import DummyServiceBase, DummyServiceStub


class DummyService(DummyServiceBase):

    def __init__(self):
        self.log = []

    async def UnaryUnary(self, stream):
        request = await stream.recv_message()
        self.log.append(request)
        await stream.send_message(DummyReply(value='pong'))

    async def UnaryStream(self, stream):
        request = await stream.recv_message()
        self.log.append(request)
        assert await stream.recv_message() is None
        await stream.send_message(DummyReply(value='pong1'))
        await stream.send_message(DummyReply(value='pong2'))
        await stream.send_message(DummyReply(value='pong3'))

    async def StreamUnary(self, stream):
        async for request in stream:
            self.log.append(request)
        await stream.send_message(DummyReply(value='pong'))

    async def StreamStream(self, stream):
        async for request in stream:
            self.log.append(request)
            await stream.send_message(DummyReply(value=request.value))


class ClientServer:
    server = None
    channel = None

    def __init__(self, *, loop):
        self.loop = loop

    async def __aenter__(self):
        host = '127.0.0.1'
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            _, port = s.getsockname()

        dummy_service = DummyService()

        self.server = Server([dummy_service], loop=self.loop)
        await self.server.start(host, port)

        self.channel = Channel(host=host, port=port, loop=self.loop)
        dummy_stub = DummyServiceStub(self.channel)
        return dummy_service, dummy_stub

    async def __aexit__(self, *exc_info):
        self.server.close()
        await self.server.wait_closed()
        self.channel.close()


class UnixClientServer:
    temp = None
    sock = None
    server = None
    channel = None

    def __init__(self, *, loop):
        self.loop = loop

    async def __aenter__(self):
        self.temp = tempfile.mkdtemp()
        self.sock = os.path.join(self.temp, 'grpclib.sock')

        dummy_service = DummyService()

        self.server = Server([dummy_service], loop=self.loop)
        await self.server.start(path=self.sock)

        self.channel = Channel(path=self.sock, loop=self.loop)
        dummy_stub = DummyServiceStub(self.channel)
        return dummy_service, dummy_stub

    async def __aexit__(self, *exc_info):
        self.server.close()
        await self.server.wait_closed()
        self.channel.close()
        if os.path.exists(self.sock):
            os.unlink(self.sock)
        if os.path.exists(self.temp):
            os.rmdir(self.temp)


@pytest.mark.asyncio
async def test_close_empty_channel(loop):
    async with ClientServer(loop=loop):
        """it should not raise exceptions"""


@pytest.mark.asyncio
async def test_unary_unary_simple(loop):
    async with ClientServer(loop=loop) as (handler, stub):
        reply = await stub.UnaryUnary(DummyRequest(value='ping'))
        assert reply == DummyReply(value='pong')
        assert handler.log == [DummyRequest(value='ping')]


@pytest.mark.asyncio
async def test_unary_unary_simple_unix(loop):
    async with UnixClientServer(loop=loop) as (handler, stub):
        reply = await stub.UnaryUnary(DummyRequest(value='ping'))
        assert reply == DummyReply(value='pong')
        assert handler.log == [DummyRequest(value='ping')]


@pytest.mark.asyncio
async def test_unary_unary_advanced(loop):
    async with ClientServer(loop=loop) as (handler, stub):
        async with stub.UnaryUnary.open() as stream:
            await stream.send_message(DummyRequest(value='ping'), end=True)
            reply = await stream.recv_message()
        assert reply == DummyReply(value='pong')
        assert handler.log == [DummyRequest(value='ping')]


@pytest.mark.asyncio
async def test_unary_stream_simple(loop):
    async with ClientServer(loop=loop) as (handler, stub):
        replies = await stub.UnaryStream(DummyRequest(value='ping'))
        assert handler.log == [DummyRequest(value='ping')]
        assert replies == [DummyReply(value='pong1'),
                           DummyReply(value='pong2'),
                           DummyReply(value='pong3')]


@pytest.mark.asyncio
async def test_unary_stream_advanced(loop):
    async with ClientServer(loop=loop) as (handler, stub):
        async with stub.UnaryStream.open() as stream:
            await stream.send_message(DummyRequest(value='ping'), end=True)
            replies = [message async for message in stream]
        assert handler.log == [DummyRequest(value='ping')]
        assert replies == [DummyReply(value='pong1'),
                           DummyReply(value='pong2'),
                           DummyReply(value='pong3')]


@pytest.mark.asyncio
async def test_stream_unary_simple(loop):
    async with ClientServer(loop=loop) as (handler, stub):
        reply = await stub.StreamUnary([
            DummyRequest(value='ping1'),
            DummyRequest(value='ping2'),
            DummyRequest(value='ping3'),
        ])
        assert reply == DummyReply(value='pong')
        assert handler.log == [DummyRequest(value='ping1'),
                               DummyRequest(value='ping2'),
                               DummyRequest(value='ping3')]


@pytest.mark.asyncio
async def test_stream_unary_advanced(loop):
    async with ClientServer(loop=loop) as (handler, stub):
        async with stub.StreamUnary.open() as stream:
            await stream.send_message(DummyRequest(value='ping1'))
            await stream.send_message(DummyRequest(value='ping2'))
            await stream.send_message(DummyRequest(value='ping3'), end=True)
            reply = await stream.recv_message()
        assert reply == DummyReply(value='pong')
        assert handler.log == [DummyRequest(value='ping1'),
                               DummyRequest(value='ping2'),
                               DummyRequest(value='ping3')]


@pytest.mark.asyncio
async def test_stream_stream_simple(loop):
    async with ClientServer(loop=loop) as (_, stub):
        replies = await stub.StreamStream([
            DummyRequest(value='foo'),
            DummyRequest(value='bar'),
            DummyRequest(value='baz'),
        ])
        assert replies == [
            DummyReply(value='foo'),
            DummyReply(value='bar'),
            DummyReply(value='baz'),
        ]


@pytest.mark.asyncio
async def test_stream_stream_advanced(loop):
    async with ClientServer(loop=loop) as (_, stub):
        async with stub.StreamStream.open() as stream:
            await stream.send_message(DummyRequest(value='foo'))
            assert await stream.recv_message() == DummyReply(value='foo')

            await stream.send_message(DummyRequest(value='bar'))
            assert await stream.recv_message() == DummyReply(value='bar')

            await stream.send_message(DummyRequest(value='baz'), end=True)
            assert await stream.recv_message() == DummyReply(value='baz')

            assert await stream.recv_message() is None
