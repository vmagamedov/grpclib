import socket

import pytest

from grpclib.client import Channel, _to_list
from grpclib.server import Server

from bombed_pb2 import SavoysRequest, SavoysReply
from bombed_pb2 import UnyoungChunk, GoowyChunk
from bombed_grpc import BombedBase, BombedStub


class Bombed(BombedBase):

    def __init__(self):
        self.log = []

    async def Plaster(self, stream):
        request = await stream.recv_message()
        self.log.append(request)
        await stream.send_message(SavoysReply(benito='bebops'))

    async def Benzine(self, stream):
        request = await stream.recv_message()
        self.log.append(request)
        assert await stream.recv_message() is None
        await stream.send_message(GoowyChunk(biomes='papists'))
        await stream.send_message(GoowyChunk(biomes='tip'))
        await stream.send_message(GoowyChunk(biomes='off'))
        await stream.send_message(GoowyChunk(biomes='popo' * 65535))

    async def Anginal(self, stream):
        async for request in stream:
            self.log.append(request)
        await stream.send_message(SavoysReply(benito='anagogy'))

    async def Devilry(self, stream):
        async for request in stream:
            self.log.append(request)
            await stream.send_message(GoowyChunk(biomes=request.whome))


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

        bombed = Bombed()

        self.server = Server([bombed], loop=self.loop)
        await self.server.start(host, port)

        self.channel = Channel(host=host, port=port, loop=self.loop)
        stub = BombedStub(self.channel)
        return bombed, stub

    async def __aexit__(self, *exc_info):
        self.server.close()
        await self.server.wait_closed()
        self.channel.close()


@pytest.mark.asyncio
async def test_close_empty_channel(loop):
    async with ClientServer(loop=loop):
        """it should not raise exceptions"""


@pytest.mark.asyncio
async def test_unary_unary_simple(loop):
    async with ClientServer(loop=loop) as (handler, stub):
        reply = await stub.Plaster(SavoysRequest(kyler='huizhou'))
        assert reply == SavoysReply(benito='bebops')
        assert handler.log == [SavoysRequest(kyler='huizhou')]


@pytest.mark.asyncio
async def test_unary_unary_simple_long(loop):
    async with ClientServer(loop=loop) as (handler, stub):
        reply = await stub.Plaster(SavoysRequest(kyler='popo' * 65535))
        assert reply == SavoysReply(benito='bebops')
        assert handler.log == [SavoysRequest(kyler='huizhou')]


@pytest.mark.asyncio
async def test_unary_unary_advanced(loop):
    async with ClientServer(loop=loop) as (handler, stub):
        async with stub.Plaster.open() as stream:
            await stream.send_message(SavoysRequest(kyler='huizhou'))
            reply = await stream.recv_message()
        assert reply == SavoysReply(benito='bebops')
        assert handler.log == [SavoysRequest(kyler='huizhou')]


@pytest.mark.asyncio
async def test_unary_stream_simple(loop):
    async with ClientServer(loop=loop) as (handler, stub):
        replies = await stub.Benzine(SavoysRequest(kyler='eediot'))
        assert handler.log == [SavoysRequest(kyler='eediot')]
        assert replies == [GoowyChunk(biomes='papists'),
                           GoowyChunk(biomes='tip'),
                           GoowyChunk(biomes='off')]


@pytest.mark.asyncio
async def test_unary_stream_advanced(loop):
    async with ClientServer(loop=loop) as (handler, stub):
        async with stub.Benzine.open() as stream:
            await stream.send_message(SavoysRequest(kyler='eediot'), end=True)
            replies = await _to_list(stream)
        assert handler.log == [SavoysRequest(kyler='eediot')]
        assert replies == [GoowyChunk(biomes='papists'),
                           GoowyChunk(biomes='tip'),
                           GoowyChunk(biomes='off')]


@pytest.mark.asyncio
async def test_stream_unary_simple(loop):
    async with ClientServer(loop=loop) as (handler, stub):
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
async def test_stream_unary_advanced(loop):
    async with ClientServer(loop=loop) as (handler, stub):
        async with stub.Anginal.open() as stream:
            await stream.send_message(UnyoungChunk(whome='canopy'))
            await stream.send_message(UnyoungChunk(whome='iver'))
            await stream.send_message(UnyoungChunk(whome='part'), end=True)
            reply = await stream.recv_message()
        assert reply == SavoysReply(benito='anagogy')
        assert handler.log == [UnyoungChunk(whome='canopy'),
                               UnyoungChunk(whome='iver'),
                               UnyoungChunk(whome='part')]


@pytest.mark.asyncio
async def test_stream_stream_simple(loop):
    async with ClientServer(loop=loop) as (_, stub):
        replies = await stub.Devilry([
            UnyoungChunk(whome='guv'),
            UnyoungChunk(whome='lactic'),
            UnyoungChunk(whome='scrawn'),
            UnyoungChunk(whome='popo' * 65535),
        ])
        assert replies == [
            GoowyChunk(biomes='guv'),
            GoowyChunk(biomes='lactic'),
            GoowyChunk(biomes='scrawn'),
            GoowyChunk(biomes='popo' * 65535),
        ]


@pytest.mark.asyncio
async def test_stream_stream_advanced(loop):
    async with ClientServer(loop=loop) as (_, stub):
        async with stub.Devilry.open() as stream:
            await stream.send_message(UnyoungChunk(whome='guv'))
            assert await stream.recv_message() == GoowyChunk(biomes='guv')

            await stream.send_message(UnyoungChunk(whome='lactic'))
            assert await stream.recv_message() == GoowyChunk(biomes='lactic')

            await stream.send_message(UnyoungChunk(whome='scrawn'), end=True)
            assert await stream.recv_message() == GoowyChunk(biomes='scrawn')

            long_pop = 'popo' * 65535
            await stream.send_message(UnyoungChunk(whome=long_pop), end=True)
            assert await stream.recv_message() == GoowyChunk(biomes=long_pop)

            assert await stream.recv_message() is None
