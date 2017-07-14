import socket
import asyncio

import pytest

from grpclib.client import Channel
from grpclib.server import Server

from .protobuf.testing_pb2 import SavoysRequest, SavoysReply
from .protobuf.testing_pb2 import UnyoungChunk, GoowyChunk
from .protobuf.testing_grpc import BombedService, BombedServiceStub


class Bombed(BombedService):

    def __init__(self):
        self.log = []

    async def Plaster(self, request, context):
        self.log.append(request)
        return SavoysReply(benito='bebops')

    async def Anginal(self, request_stream, context):
        async for request in request_stream:
            self.log.append(request)
        return SavoysReply(benito='anagogy')

    async def Benzine(self, request, context):
        self.log.append(request)
        yield GoowyChunk(biomes='papists')
        yield GoowyChunk(biomes='tip')
        yield GoowyChunk(biomes='off')

    async def Devilry(self, request_stream, context):
        async for request in request_stream:
            self.log.append(request)
            yield GoowyChunk(biomes=request.whome)


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
        stub = BombedServiceStub(channel)
        return bombed, stub

    async def __aexit__(self, *exc_info):
        self.server.close()
        await self.server.wait_closed()


@pytest.mark.asyncio
async def test_unary_unary(event_loop):
    async with ClientServer(loop=event_loop) as (bombed, stub):
        reply = await stub.Plaster(SavoysRequest(kyler='huizhou'))
        assert reply == SavoysReply(benito='bebops')
        assert bombed.log == [SavoysRequest(kyler='huizhou')]


@pytest.mark.asyncio
async def test_stream_unary(event_loop):
    async with ClientServer(loop=event_loop) as (bombed, stub):

        async def upload_gen():
            yield UnyoungChunk(whome='canopy')
            yield UnyoungChunk(whome='iver')
            yield UnyoungChunk(whome='part')

        reply = await stub.Anginal(upload_gen())
        assert reply == SavoysReply(benito='anagogy')
        assert bombed.log == [UnyoungChunk(whome='canopy'),
                              UnyoungChunk(whome='iver'),
                              UnyoungChunk(whome='part')]


@pytest.mark.asyncio
async def test_unary_stream(event_loop):
    async with ClientServer(loop=event_loop) as (bombed, stub):
        reply_stream = await stub.Benzine(SavoysRequest(kyler='eediot'))
        assert bombed.log == [SavoysRequest(kyler='eediot')]
        reply = [r async for r in reply_stream]
        assert reply == [GoowyChunk(biomes='papists'),
                         GoowyChunk(biomes='tip'),
                         GoowyChunk(biomes='off')]


class Upstream:

    def __init__(self, *, loop):
        self._queue = asyncio.Queue(loop=loop)

    async def send(self, item):
        await self._queue.put(item)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        await self._queue.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self._queue.get()
        if item is None:
            raise StopAsyncIteration()
        else:
            return item


@pytest.mark.skip
@pytest.mark.asyncio
async def test_stream_stream(event_loop):
    async with ClientServer(loop=event_loop) as (bombed, stub):
        async with Upstream(loop=event_loop) as upstream:
            downstream = (await stub.Devilry(upstream)).__aiter__()

            await upstream.send(UnyoungChunk(whome='guv'))
            assert await downstream.__anext__() == GoowyChunk(biomes='guv')

            await upstream.send(UnyoungChunk(whome='lactic'))
            assert await downstream.__anext__() == GoowyChunk(biomes='lactic')

            await upstream.send(UnyoungChunk(whome='scrawn'))
            assert await downstream.__anext__() == GoowyChunk(biomes='scrawn')

        with pytest.raises(StopAsyncIteration):
            await downstream.__anext__()
