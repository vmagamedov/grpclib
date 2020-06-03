import time
import asyncio
from unittest.mock import patch

import pytest

from grpclib.const import Status
from grpclib.client import _ChannelState, Channel
from grpclib.testing import ChannelFor
from grpclib.exceptions import GRPCError

from dummy_pb2 import DummyRequest, DummyReply
from dummy_grpc import DummyServiceBase, DummyServiceStub


def _is_recent(value):
    assert time.monotonic() - value < 1


class DummyService(DummyServiceBase):

    async def UnaryUnary(self, stream):
        raise GRPCError(Status.UNIMPLEMENTED)

    async def UnaryStream(self, stream):
        raise GRPCError(Status.UNIMPLEMENTED)

    async def StreamUnary(self, stream):
        raise GRPCError(Status.UNIMPLEMENTED)

    async def StreamStream(self, stream):
        raise GRPCError(Status.UNIMPLEMENTED)


class WorkingDummyService(DummyService):
    async def UnaryUnary(self, stream):
        await stream.recv_message()
        await stream.send_message(DummyReply(value='test'))


class FailingDummyService(DummyService):
    async def UnaryUnary(self, stream):
        raise Exception('unexpected')


@pytest.mark.asyncio
async def test_channel_calls_succeeded():
    async with ChannelFor([WorkingDummyService()]) as channel:
        stub = DummyServiceStub(channel)

        assert channel._calls_started == 0
        assert channel._calls_succeeded == 0
        assert channel._calls_failed == 0
        assert channel._last_call_started is None

        reply = await stub.UnaryUnary(DummyRequest(value='whatever'))

        assert channel._calls_started == 1
        assert channel._calls_succeeded == 1
        assert channel._calls_failed == 0
        _is_recent(channel._last_call_started)

    assert reply == DummyReply(value='test')


@pytest.mark.asyncio
async def test_channel_calls_failed():
    async with ChannelFor([FailingDummyService()]) as channel:
        stub = DummyServiceStub(channel)

        assert channel._calls_started == 0
        assert channel._calls_succeeded == 0
        assert channel._calls_failed == 0
        assert channel._last_call_started is None

        with pytest.raises(GRPCError, match='Internal Server Error'):
            await stub.UnaryUnary(DummyRequest(value='whatever'))

        assert channel._calls_started == 1
        assert channel._calls_succeeded == 0
        assert channel._calls_failed == 1
        _is_recent(channel._last_call_started)


@pytest.mark.asyncio
async def test_channel_ready(loop):
    async with ChannelFor([WorkingDummyService()]) as _channel:
        channel = Channel()

        async def _create_connection():
            await asyncio.sleep(0.01)
            return _channel._protocol

        with patch.object(channel, '_create_connection', _create_connection):
            assert channel._state is _ChannelState.IDLE
            connect_task = loop.create_task(channel.__connect__())
            await asyncio.sleep(0.001)
            assert channel._state is _ChannelState.CONNECTING
            await connect_task
            assert channel._state is _ChannelState.READY

        channel.close()
        assert channel._state is _ChannelState.IDLE


@pytest.mark.asyncio
async def test_channel_transient_failure(loop):
    channel = Channel()

    async def _create_connection():
        await asyncio.sleep(0.01)
        raise asyncio.TimeoutError('try again later')

    with patch.object(channel, '_create_connection', _create_connection):
        assert channel._state is _ChannelState.IDLE
        connect_task = loop.create_task(channel.__connect__())
        await asyncio.sleep(0.001)
        assert channel._state is _ChannelState.CONNECTING
        with pytest.raises(asyncio.TimeoutError, match='try again later'):
            await connect_task
        assert channel._state is _ChannelState.TRANSIENT_FAILURE

    channel.close()
    assert channel._state is _ChannelState.IDLE


@pytest.mark.asyncio
async def test_client_stream():
    async with ChannelFor([WorkingDummyService()]) as channel:
        proto = await channel.__connect__()
        stub = DummyServiceStub(channel)

        async with stub.UnaryUnary.open() as stream:
            assert proto.connection.streams_started == 0
            assert proto.connection.streams_succeeded == 0
            assert proto.connection.streams_failed == 0
            assert proto.connection.last_stream_created is None
            await stream.send_request()
            _is_recent(stream._stream.created)

            assert proto.connection.streams_started == 1
            assert proto.connection.streams_succeeded == 0
            assert proto.connection.streams_failed == 0
            _is_recent(proto.connection.last_stream_created)

            assert stream._messages_sent == 0
            assert stream._stream.data_sent == 0
            assert proto.connection.messages_sent == 0
            assert proto.connection.data_sent == 0
            assert proto.connection.last_message_sent is None
            await stream.send_message(DummyRequest(value='whatever'), end=True)
            assert stream._messages_sent == 1
            assert stream._stream.data_sent > 0
            assert proto.connection.messages_sent == 1
            assert proto.connection.data_sent > 0
            _is_recent(proto.connection.last_message_sent)
            _is_recent(proto.connection.last_data_sent)

            assert stream._messages_received == 0
            assert stream._stream.data_received == 0
            assert proto.connection.messages_received == 0
            assert proto.connection.data_received == 0
            assert proto.connection.last_message_received is None
            reply = await stream.recv_message()
            assert stream._messages_received == 1
            assert stream._stream.data_received > 0
            assert proto.connection.messages_received == 1
            assert proto.connection.data_received > 0
            _is_recent(proto.connection.last_message_received)
            _is_recent(proto.connection.last_data_received)

        assert proto.connection.streams_started == 1
        assert proto.connection.streams_succeeded == 1
        assert proto.connection.streams_failed == 0
    assert reply == DummyReply(value='test')


@pytest.mark.asyncio
async def test_server_stream():
    cf = ChannelFor([WorkingDummyService()])
    async with cf as channel:
        stub = DummyServiceStub(channel)
        handler, = cf._server._handlers

        async with stub.UnaryUnary.open() as stream:
            await stream.send_request()
            while not handler._tasks:
                await asyncio.sleep(0.001)

            server_stream, = handler._tasks.keys()
            _is_recent(server_stream.created)
            assert server_stream.data_sent == 0
            assert server_stream.data_received == 0
            assert server_stream.connection.messages_sent == 0
            assert server_stream.connection.messages_received == 0
            assert server_stream.connection.last_message_sent is None
            assert server_stream.connection.last_message_received is None
            await stream.send_message(DummyRequest(value='whatever'), end=True)
            await asyncio.sleep(0.01)
            assert server_stream.data_sent > 0
            assert server_stream.data_received > 0
            assert server_stream.connection.messages_sent == 1
            assert server_stream.connection.messages_received == 1
            _is_recent(server_stream.connection.last_data_sent)
            _is_recent(server_stream.connection.last_data_received)
            _is_recent(server_stream.connection.last_message_sent)
            _is_recent(server_stream.connection.last_message_received)

            reply = await stream.recv_message()
    assert reply == DummyReply(value='test')
