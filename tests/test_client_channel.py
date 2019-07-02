import asyncio
from unittest.mock import patch, ANY

import pytest

from grpclib.client import Channel
from grpclib.testing import ChannelFor

from dummy_pb2 import DummyRequest, DummyReply
from dummy_grpc import DummyServiceStub
from test_functional import DummyService


async def _create_connection(protocol):
    await asyncio.sleep(0.01)
    return None, protocol


def _create_connection_gen(protocol):
    while True:
        yield _create_connection(protocol)


@pytest.mark.asyncio
async def test_concurrent_connect(loop):
    count = 5
    reqs = [DummyRequest(value='ping') for _ in range(count)]
    reps = [DummyReply(value='pong') for _ in range(count)]

    channel = Channel(loop=loop)
    stub = DummyServiceStub(channel)
    async with ChannelFor([DummyService()]) as _channel:
        with patch.object(loop, 'create_connection') as po:
            po.side_effect = _create_connection_gen(_channel._current_protocol)
            tasks = [loop.create_task(stub.UnaryUnary(req)) for req in reqs]
            replies = await asyncio.gather(*tasks)
    assert replies == reps
    po.assert_called_once_with(ANY, '127.0.0.1', 50051, ssl=None)
