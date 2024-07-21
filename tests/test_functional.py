import os
import socket
import tempfile
import ipaddress

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
    server_ctx = None
    channel = None
    channel_ctx = None

    def __init__(self, *, host="127.0.0.1"):
        self.host = host

    async def __aenter__(self):
        try:
            ipaddress.IPv6Address(self.host)
        except ipaddress.AddressValueError:
            family = socket.AF_INET
        else:
            family = socket.AF_INET6
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.bind((self.host, 0))
            _, port, *_ = s.getsockname()

        dummy_service = DummyService()

        self.server = Server([dummy_service])
        await self.server.start(self.host, port)
        self.server_ctx = await self.server.__aenter__()

        self.channel = Channel(host=self.host, port=port)
        self.channel_ctx = await self.channel.__aenter__()
        dummy_stub = DummyServiceStub(self.channel)
        return dummy_service, dummy_stub

    async def __aexit__(self, *exc_info):
        await self.channel_ctx.__aexit__(*exc_info)
        await self.server_ctx.__aexit__(*exc_info)


class UnixClientServer:
    temp = None
    sock = None
    server = None
    server_ctx = None
    channel = None
    channel_ctx = None

    async def __aenter__(self):
        self.temp = tempfile.mkdtemp()
        self.sock = os.path.join(self.temp, 'grpclib.sock')

        dummy_service = DummyService()

        self.server = Server([dummy_service])
        await self.server.start(path=self.sock)
        self.server_ctx = await self.server.__aenter__()

        self.channel = Channel(path=self.sock)
        self.channel_ctx = await self.channel.__aenter__()
        dummy_stub = DummyServiceStub(self.channel)
        return dummy_service, dummy_stub

    async def __aexit__(self, *exc_info):
        await self.channel_ctx.__aexit__(*exc_info)
        await self.server_ctx.__aexit__(*exc_info)
        if os.path.exists(self.sock):
            os.unlink(self.sock)
        if os.path.exists(self.temp):
            os.rmdir(self.temp)


@pytest.mark.asyncio
async def test_close_empty_channel():
    async with ClientServer():
        """it should not raise exceptions"""


@pytest.mark.asyncio
async def test_unary_unary_simple():
    async with ClientServer() as (handler, stub):
        reply = await stub.UnaryUnary(DummyRequest(value='ping'))
        assert reply == DummyReply(value='pong')
        assert handler.log == [DummyRequest(value='ping')]


@pytest.mark.asyncio
async def test_unary_unary_simple_unix():
    async with UnixClientServer() as (handler, stub):
        reply = await stub.UnaryUnary(DummyRequest(value='ping'))
        assert reply == DummyReply(value='pong')
        assert handler.log == [DummyRequest(value='ping')]


@pytest.mark.asyncio
async def test_unary_unary_advanced():
    async with ClientServer() as (handler, stub):
        async with stub.UnaryUnary.open() as stream:
            await stream.send_message(DummyRequest(value='ping'), end=True)
            reply = await stream.recv_message()
        assert reply == DummyReply(value='pong')
        assert handler.log == [DummyRequest(value='ping')]


@pytest.mark.asyncio
async def test_unary_stream_simple():
    async with ClientServer() as (handler, stub):
        replies = await stub.UnaryStream(DummyRequest(value='ping'))
        assert handler.log == [DummyRequest(value='ping')]
        assert replies == [DummyReply(value='pong1'),
                           DummyReply(value='pong2'),
                           DummyReply(value='pong3')]


@pytest.mark.asyncio
async def test_unary_stream_advanced():
    async with ClientServer() as (handler, stub):
        async with stub.UnaryStream.open() as stream:
            await stream.send_message(DummyRequest(value='ping'), end=True)
            replies = [message async for message in stream]
        assert handler.log == [DummyRequest(value='ping')]
        assert replies == [DummyReply(value='pong1'),
                           DummyReply(value='pong2'),
                           DummyReply(value='pong3')]


@pytest.mark.asyncio
async def test_stream_unary_simple():
    async with ClientServer() as (handler, stub):
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
async def test_stream_unary_advanced():
    async with ClientServer() as (handler, stub):
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
async def test_stream_stream_simple():
    async with ClientServer() as (_, stub):
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
async def test_stream_stream_advanced():
    async with ClientServer() as (_, stub):
        async with stub.StreamStream.open() as stream:
            await stream.send_message(DummyRequest(value='foo'))
            assert await stream.recv_message() == DummyReply(value='foo')

            await stream.send_message(DummyRequest(value='bar'))
            assert await stream.recv_message() == DummyReply(value='bar')

            await stream.send_message(DummyRequest(value='baz'), end=True)
            assert await stream.recv_message() == DummyReply(value='baz')

            assert await stream.recv_message() is None


@pytest.mark.asyncio
@pytest.mark.skipif(not socket.has_ipv6, reason="No IPv6 support")
async def test_ipv6():
    async with ClientServer(host="::1") as (handler, stub):
        reply = await stub.UnaryUnary(DummyRequest(value='ping'))
        assert reply == DummyReply(value='pong')
        assert handler.log == [DummyRequest(value='ping')]
