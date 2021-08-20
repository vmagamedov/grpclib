import pytest

from multidict import MultiDict
from google.rpc.error_details_pb2 import ResourceInfo

from grpclib.const import Status
from grpclib.events import listen, RecvRequest, RecvMessage, SendMessage
from grpclib.events import SendInitialMetadata, SendTrailingMetadata
from grpclib.exceptions import GRPCError
from grpclib.testing import ChannelFor

from dummy_pb2 import DummyRequest, DummyReply
from dummy_grpc import DummyServiceStub, DummyServiceBase


class DummyService(DummyServiceBase):

    async def UnaryUnary(self, stream):
        await stream.recv_message()
        await stream.send_initial_metadata(metadata={'initial': 'true'})
        await stream.send_message(DummyReply(value='pong'))
        await stream.send_trailing_metadata(
            metadata={'trailing': 'true'},
            status=Status.OK,
            status_message="Everything is OK",
            status_details=[ResourceInfo()],
        )

    async def UnaryStream(self, stream):
        raise GRPCError(Status.UNIMPLEMENTED)

    async def StreamUnary(self, stream):
        raise GRPCError(Status.UNIMPLEMENTED)

    async def StreamStream(self, stream):
        raise GRPCError(Status.UNIMPLEMENTED)


async def _test(event_type):
    service = DummyService()
    events = []

    async def callback(event_):
        events.append(event_)

    channel_for = ChannelFor([service])
    async with channel_for as channel:
        server = channel_for._server

        listen(server, event_type, callback)
        stub = DummyServiceStub(channel)
        reply = await stub.UnaryUnary(DummyRequest(value='ping'),
                                      timeout=1,
                                      metadata={'foo': 'bar'})
        assert reply == DummyReply(value='pong')

    event, = events
    return event


@pytest.mark.asyncio
async def test_recv_request():
    event = await _test(RecvRequest)
    assert event.metadata == MultiDict({'foo': 'bar'})
    assert event.method_name == '/dummy.DummyService/UnaryUnary'
    assert event.deadline.time_remaining() > 0
    assert event.content_type == 'application/grpc'
    assert event.user_agent.startswith('grpc-python-grpclib')
    assert event.peer.addr() is None


@pytest.mark.asyncio
async def test_recv_message():
    event = await _test(RecvMessage)
    assert event.message == DummyRequest(value='ping')


@pytest.mark.asyncio
async def test_send_message():
    event = await _test(SendMessage)
    assert event.message == DummyReply(value='pong')


@pytest.mark.asyncio
async def test_send_initial_metadata():
    event = await _test(SendInitialMetadata)
    assert event.metadata == MultiDict({'initial': 'true'})


@pytest.mark.asyncio
async def test_send_trailing_metadata():
    event = await _test(SendTrailingMetadata)
    assert event.metadata == MultiDict({'trailing': 'true'})
    assert event.status is Status.OK
    assert event.status_message == "Everything is OK"
    assert isinstance(event.status_details[0], ResourceInfo)
