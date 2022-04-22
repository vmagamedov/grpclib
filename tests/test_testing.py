import asyncio

import pytest

from grpclib import GRPCError, Status
from grpclib.testing import ChannelFor

from dummy_pb2 import DummyRequest, DummyReply
from dummy_grpc import DummyServiceStub
from test_functional import DummyService


@pytest.mark.asyncio
async def test():
    async with ChannelFor([DummyService()]) as channel:
        stub = DummyServiceStub(channel)
        reply = await stub.UnaryUnary(DummyRequest(value='ping'))
        assert reply == DummyReply(value='pong')


@pytest.mark.asyncio
async def test_failure():
    class FailingService(DummyService):
        async def UnaryUnary(self, stream):
            raise GRPCError(Status.FAILED_PRECONDITION)

    async with ChannelFor([FailingService()]) as channel:
        stub = DummyServiceStub(channel)
        with pytest.raises(GRPCError) as err:
            await stub.UnaryUnary(DummyRequest(value='ping'))
        assert err.value.status is Status.FAILED_PRECONDITION


@pytest.mark.asyncio
async def test_timeout(caplog):
    async with ChannelFor([DummyService()]) as channel:
        stub = DummyServiceStub(channel)
        with pytest.raises(asyncio.TimeoutError):
            await stub.UnaryUnary(DummyRequest(value='ping'), timeout=-1)
    assert not caplog.records
