import socket

import pytest

from grpclib.client import Channel
from grpclib.server import Server

from .protobuf.testing_pb2 import SavoysRequest, SavoysReply
from .protobuf.testing_pb2 import UnyoungChunk, GoowyChunk
from .protobuf.testing_grpc import BombedBase, BombedStub


class Bombed(BombedBase):

    def __init__(self):
        self.log = []

    async def Plaster(self, stream):
        request = await stream.recv()
        self.log.append(request)
        await stream.send(SavoysReply(benito='bebops'))

    async def Benzine(self, stream):
        request = await stream.recv()
        self.log.append(request)
        assert await stream.recv() is None
        await stream.send(GoowyChunk(biomes='papists'))
        await stream.send(GoowyChunk(biomes='tip'))
        await stream.send(GoowyChunk(biomes='off'))

    async def Anginal(self, stream):
        async for request in stream:
            self.log.append(request)
        await stream.send(SavoysReply(benito='anagogy'))

    async def Devilry(self, stream):
        async for request in stream:
            self.log.append(request)
            await stream.send(GoowyChunk(biomes=request.whome))


class ClientServer:
    server = None

    def __init__(self, *, loop):
        self.loop = loop

    async def __aenter__(self):
        host = '127.0.0.1'
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            _, port = s.getsockname()

        bombed = Bombed()

        self.server = Server([bombed], loop=self.loop)
        await self.server.start(host, port)

        channel = Channel(host=host, port=port, loop=self.loop)
        stub = BombedStub(channel)
        return bombed, stub

    async def __aexit__(self, *exc_info):
        self.server.close()
        await self.server.wait_closed()


@pytest.mark.asyncio
async def test_unary_unary_simple(event_loop):
    async with ClientServer(loop=event_loop) as (handler, stub):
        reply = await stub.Plaster(SavoysRequest(kyler='huizhou'))
        assert reply == SavoysReply(benito='bebops')
        assert handler.log == [SavoysRequest(kyler='huizhou')]


@pytest.mark.asyncio
async def test_unary_unary_advanced(event_loop):
    async with ClientServer(loop=event_loop) as (handler, stub):
        async with stub.Plaster.open() as stream:
            await stream.send(SavoysRequest(kyler='huizhou'))
            reply = await stream.recv()
        assert reply == SavoysReply(benito='bebops')
        assert handler.log == [SavoysRequest(kyler='huizhou')]


@pytest.mark.asyncio
async def test_unary_stream_simple(event_loop):
    async with ClientServer(loop=event_loop) as (handler, stub):
        replies = await stub.Benzine(SavoysRequest(kyler='eediot'))
        assert handler.log == [SavoysRequest(kyler='eediot')]
        assert replies == [GoowyChunk(biomes='papists'),
                           GoowyChunk(biomes='tip'),
                           GoowyChunk(biomes='off')]


@pytest.mark.asyncio
async def test_unary_stream_advanced(event_loop):
    async with ClientServer(loop=event_loop) as (handler, stub):
        async with stub.Benzine.open() as stream:
            await stream.send(SavoysRequest(kyler='eediot'), end=True)
            replies = [r async for r in stream]
        assert handler.log == [SavoysRequest(kyler='eediot')]
        assert replies == [GoowyChunk(biomes='papists'),
                           GoowyChunk(biomes='tip'),
                           GoowyChunk(biomes='off')]


@pytest.mark.asyncio
async def test_stream_unary_simple(event_loop):
    async with ClientServer(loop=event_loop) as (handler, stub):
        reply = await stub.Anginal([
            UnyoungChunk(whome='canopy'),
            UnyoungChunk(whome='iver'),
            UnyoungChunk(whome='part'),
        ])
        assert reply == SavoysReply(benito='anagogy')
        assert handler.log == [UnyoungChunk(whome='canopy'),
                               UnyoungChunk(whome='iver'),
                               UnyoungChunk(whome='part')]


@pytest.mark.asyncio
async def test_stream_unary_advanced(event_loop):
    async with ClientServer(loop=event_loop) as (handler, stub):
        async with stub.Anginal.open() as stream:
            await stream.send(UnyoungChunk(whome='canopy'))
            await stream.send(UnyoungChunk(whome='iver'))
            await stream.send(UnyoungChunk(whome='part'), end=True)
            reply = await stream.recv()
        assert reply == SavoysReply(benito='anagogy')
        assert handler.log == [UnyoungChunk(whome='canopy'),
                               UnyoungChunk(whome='iver'),
                               UnyoungChunk(whome='part')]


@pytest.mark.asyncio
async def test_stream_stream_simple(event_loop):
    async with ClientServer(loop=event_loop) as (_, stub):
        replies = await stub.Devilry([
            UnyoungChunk(whome='guv'),
            UnyoungChunk(whome='lactic'),
            UnyoungChunk(whome='scrawn'),
        ])
        assert replies == [
            GoowyChunk(biomes='guv'),
            GoowyChunk(biomes='lactic'),
            GoowyChunk(biomes='scrawn'),
        ]


@pytest.mark.asyncio
async def test_stream_stream_advanced(event_loop):
    async with ClientServer(loop=event_loop) as (_, stub):
        async with stub.Devilry.open() as stream:
            await stream.send(UnyoungChunk(whome='guv'))
            assert await stream.recv() == GoowyChunk(biomes='guv')

            await stream.send(UnyoungChunk(whome='lactic'))
            assert await stream.recv() == GoowyChunk(biomes='lactic')

            await stream.send(UnyoungChunk(whome='scrawn'), end=True)
            assert await stream.recv() == GoowyChunk(biomes='scrawn')

            assert await stream.recv() is None
