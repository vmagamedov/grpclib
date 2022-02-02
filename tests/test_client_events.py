from contextlib import nullcontext

import pytest

from multidict import MultiDict
from google.rpc.error_details_pb2 import ResourceInfo

from grpclib.const import Status
from grpclib.events import listen, SendRequest, SendMessage, RecvMessage
from grpclib.events import RecvInitialMetadata, RecvTrailingMetadata
from grpclib.testing import ChannelFor
from grpclib.exceptions import GRPCError

from dummy_pb2 import DummyRequest, DummyReply
from dummy_grpc import DummyServiceStub, DummyServiceBase


class DummyService(DummyServiceBase):

    def __init__(self, fail=False):
        self.fail = fail

    async def UnaryUnary(self, stream):
        await stream.recv_message()
        await stream.send_initial_metadata(metadata={'initial': 'true'})
        await stream.send_message(DummyReply(value='pong'))
        if self.fail:
            await stream.send_trailing_metadata(
                status=Status.NOT_FOUND,
                status_message="Everything is not OK",
                status_details=[ResourceInfo()],
                metadata={'trailing': 'true'},
            )
        else:
            await stream.send_trailing_metadata(metadata={'trailing': 'true'})

    async def UnaryStream(self, stream):
        raise GRPCError(Status.UNIMPLEMENTED)

    async def StreamUnary(self, stream):
        raise GRPCError(Status.UNIMPLEMENTED)

    async def StreamStream(self, stream):
        raise GRPCError(Status.UNIMPLEMENTED)


async def _test(event_type, *, fail=False):
    service = DummyService(fail)
    events = []

    async def callback(event_):
        events.append(event_)

    async with ChannelFor([service]) as channel:
        listen(channel, event_type, callback)
        stub = DummyServiceStub(channel)

        ctx = pytest.raises(GRPCError) if fail else nullcontext()
        with ctx:
            reply = await stub.UnaryUnary(DummyRequest(value='ping'),
                                          timeout=1,
                                          metadata={'request': 'true'})
            assert reply == DummyReply(value='pong')

    event, = events
    return event


@pytest.mark.asyncio
async def test_send_request():
    event = await _test(SendRequest)
    assert event.metadata == MultiDict({'request': 'true'})
    assert event.method_name == '/dummy.DummyService/UnaryUnary'
    assert event.deadline.time_remaining() > 0
    assert event.content_type == 'application/grpc'


@pytest.mark.asyncio
async def test_send_message():
    event = await _test(SendMessage)
    assert event.message == DummyRequest(value='ping')


@pytest.mark.asyncio
async def test_recv_message():
    event = await _test(RecvMessage)
    assert event.message == DummyReply(value='pong')


@pytest.mark.asyncio
async def test_recv_initial_metadata():
    event = await _test(RecvInitialMetadata)
    assert event.metadata == MultiDict({'initial': 'true'})


@pytest.mark.asyncio
async def test_recv_trailing_metadata():
    event = await _test(RecvTrailingMetadata, fail=True)
    assert event.metadata == MultiDict({'trailing': 'true'})
    assert event.status is Status.NOT_FOUND
    assert event.status_message == "Everything is not OK"
    assert isinstance(event.status_details[0], ResourceInfo)
