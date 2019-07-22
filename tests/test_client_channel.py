import asyncio
from functools import partial
from unittest.mock import patch, ANY

import async_timeout
import pytest
from h2.config import H2Configuration
from h2.connection import H2ConnectionStateMachine, ConnectionState, H2Connection
from h2.connection import ConnectionInputs

from grpclib.client import Channel
from grpclib.exceptions import StreamTerminatedError
from grpclib.server import Server
from grpclib.testing import ChannelFor
from grpclib.protocol import _State

from dummy_pb2 import DummyRequest, DummyReply
from dummy_grpc import DummyServiceStub
from stubs import TransportStub
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


_h2_transitions_fix = H2ConnectionStateMachine._transitions.copy()
_h2_transitions_fix.update({
    (ConnectionState.CLOSED, ConnectionInputs.RECV_DATA):
        (None, ConnectionState.CLOSED),
    (ConnectionState.CLOSED, ConnectionInputs.SEND_DATA):
        (None, ConnectionState.CLOSED),
    (ConnectionState.CLOSED, ConnectionInputs.RECV_HEADERS):
        (None, ConnectionState.CLOSED),
    (ConnectionState.CLOSED, ConnectionInputs.SEND_HEADERS):
        (None, ConnectionState.CLOSED),
})


@pytest.mark.asyncio
async def test_drain(loop, addr):
    with patch.object(
        H2ConnectionStateMachine, '_transitions', _h2_transitions_fix,
    ):
        dummy_service = DummyService()
        server = Server([dummy_service], loop=loop)
        await server.start(*addr)

        channel = Channel(*addr, loop=loop)
        dummy_stub = DummyServiceStub(channel)

        async with dummy_stub.StreamUnary.open() as stream:
            await stream.send_message(DummyRequest(value='ping'))

            assert not channel._draining_protocols
            assert channel._current_protocol is not None
            current_proto = channel._current_protocol

            await asyncio.sleep(0.01)
            server.close()
            await asyncio.sleep(0.01)

            # no new connections allowed
            with pytest.raises(ConnectionRefusedError):
                await dummy_stub.UnaryUnary(DummyRequest(value='ping'))

            assert channel._draining_protocols == [current_proto]
            assert channel._current_protocol is None

            # we are able to finish current request
            await stream.send_message(DummyRequest(value='ping'), end=True)

            reply = await stream.recv_message()
            assert reply == DummyReply(value='pong')

        assert current_proto.processor.state is _State.CLOSED
        await server.wait_closed()


@pytest.fixture(name='channel')
def channel_fixture():
    async def create_connection(self):
        server_h2c = H2Connection(H2Configuration(client_side=False,
                                                  header_encoding='ascii'))
        server_h2c.initiate_connection()
        transport = TransportStub(server_h2c)
        proto = self._protocol_factory()
        proto.connection_made(transport)
        return proto

    channel = Channel()
    with patch.object(
        channel, '_create_connection', partial(create_connection, channel),
    ):
        try:
            yield channel
        finally:
            channel.close()


@pytest.mark.asyncio
async def test_max_draining(loop, channel):
    stub = DummyServiceStub(channel)

    streams = []
    for _ in range(Channel._max_draining + 1):
        stream = await stub.UnaryUnary.open().__aenter__()
        await stream.send_request()
        streams.append(stream)
        proto = channel._current_protocol
        proto.connection._transport._connection.close_connection()
        proto.data_received(
            proto.connection._transport._connection.data_to_send()
        )
        print(proto)

    assert len(channel._draining_protocols) == Channel._max_draining
    first = channel._draining_protocols[0]
    await channel.__connect__()

    assert first.connection.closed
    assert first not in channel._draining_protocols
    assert len(channel._draining_protocols) == Channel._max_draining
    assert all(not p.connection.closed for p in channel._draining_protocols)

    with pytest.raises(StreamTerminatedError, match='Max draining connections'):
        await streams[0].recv_initial_metadata()
    with pytest.raises(asyncio.TimeoutError):
        with async_timeout.timeout(0.01, loop=loop):
            await streams[1].recv_initial_metadata()
