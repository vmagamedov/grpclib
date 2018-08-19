import pytest

from grpclib.testing import channel_for

from dummy_pb2 import DummyRequest, DummyReply
from dummy_grpc import DummyServiceStub
from test_functional import DummyService


@pytest.fixture(name='stub')
def stub_fixture(loop):
    with channel_for([DummyService()], loop=loop) as channel:
        yield DummyServiceStub(channel)


@pytest.mark.asyncio
async def test(stub: DummyServiceStub):
    reply = await stub.UnaryUnary(DummyRequest(value='ping'))
    assert reply == DummyReply(value='pong')
