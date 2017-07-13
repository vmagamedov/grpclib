import socket

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


@pytest.mark.asyncio
async def test_unary_unary(event_loop):
    host = '127.0.0.1'
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        _, port = s.getsockname()

    bombed = Bombed()

    server = Server([bombed], loop=event_loop)
    await server.start(host, port)
    try:
        channel = Channel(host=host, port=port, loop=event_loop)
        stub = BombedServiceStub(channel)
        reply = await stub.Plaster(SavoysRequest(kyler='huizhou'))
        assert reply == SavoysReply(benito='bebops')
        assert bombed.log == [SavoysRequest(kyler='huizhou')]
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_stream_unary(event_loop):
    host = '127.0.0.1'
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        _, port = s.getsockname()

    bombed = Bombed()

    server = Server([bombed], loop=event_loop)
    await server.start(host, port)
    try:
        channel = Channel(host=host, port=port, loop=event_loop)
        stub = BombedServiceStub(channel)

        async def upload_gen():
            yield UnyoungChunk(whome='canopy')
            yield UnyoungChunk(whome='iver')
            yield UnyoungChunk(whome='part')

        reply = await stub.Anginal(upload_gen())
        assert reply == SavoysReply(benito='anagogy')
        assert bombed.log == [UnyoungChunk(whome='canopy'),
                              UnyoungChunk(whome='iver'),
                              UnyoungChunk(whome='part')]
    finally:
        server.close()
        await server.wait_closed()
