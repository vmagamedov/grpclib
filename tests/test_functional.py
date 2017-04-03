import socket

import pytest

from asyncgrpc.client import Channel
from asyncgrpc.server import create_server

from protobuf.testing_pb2 import SavoysRequest, SavoysReply
from protobuf.testing_grpc_pb2 import BombedService, BombedServiceStub


class Bombed(BombedService):

    def __init__(self):
        self.log = []

    async def Plaster(self, request, context):
        self.log.append(request)
        return SavoysReply(benito='bebops')


@pytest.mark.asyncio
async def test_unary_unary(event_loop):
    host = '127.0.0.1'
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        _, port = s.getsockname()

    bombed = Bombed()
    server = await create_server([bombed], host=host, port=port,
                                 loop=event_loop)
    try:
        channel = Channel(host=host, port=port, loop=event_loop)
        stub = BombedServiceStub(channel)
        reply = await stub.Plaster(SavoysRequest(kyler='huizhou'))
        assert reply == SavoysReply(benito='bebops')
        assert bombed.log == [SavoysRequest(kyler='huizhou')]
    finally:
        server.close()
        await server.wait_closed()
