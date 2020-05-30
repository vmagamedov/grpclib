import pytest

from grpclib.testing import ChannelFor

from dummy_pb2 import DummyRequest, DummyReply
from dummy_grpclib import DummyServiceStub
from test_functional import DummyService


@pytest.mark.asyncio
async def test():
    async with ChannelFor([DummyService()]) as channel:
        stub = DummyServiceStub(channel)
        reply = await stub.UnaryUnary(DummyRequest(value='ping'))
        assert reply == DummyReply(value='pong')
