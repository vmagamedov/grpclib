import sys
import asyncio
from unittest.mock import patch, ANY

import pytest

from grpclib.client import Channel
from grpclib.testing import ChannelFor

from dummy_pb2 import DummyRequest, DummyReply
from dummy_grpc import DummyServiceStub
from test_functional import DummyService


@pytest.mark.asyncio
@pytest.mark.skipif(sys.version_info < (3, 8), reason="Python < 3.8")
async def test_concurrent_connect(loop):
    count = 5
    reqs = [DummyRequest(value='ping') for _ in range(count)]
    reps = [DummyReply(value='pong') for _ in range(count)]

    channel = Channel()

    async def create_connection(*args, **kwargs):
        await asyncio.sleep(0.01)
        return None, _channel._protocol

    stub = DummyServiceStub(channel)
    async with ChannelFor([DummyService()]) as _channel:
        with patch.object(loop, 'create_connection') as po:
            po.side_effect = create_connection
            tasks = [loop.create_task(stub.UnaryUnary(req)) for req in reqs]
            replies = await asyncio.gather(*tasks)
    assert replies == reps
    po.assert_awaited_once_with(ANY, '127.0.0.1', 50051, ssl=None)


@pytest.mark.asyncio
async def test_default_ssl_context():
    certifi_channel = Channel(ssl=True)
    with patch.dict('sys.modules', {'certifi': None}):
        system_channel = Channel(ssl=True)

    certifi_certs = certifi_channel._ssl.get_ca_certs(binary_form=True)
    system_certs = system_channel._ssl.get_ca_certs(binary_form=True)

    assert certifi_certs
    assert certifi_certs != system_certs
