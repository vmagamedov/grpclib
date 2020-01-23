import asyncio
from unittest.mock import patch

import pytest

import grpclib.const
import grpclib.server
from grpclib.client import UnaryStreamMethod
from grpclib.config import Configuration
from grpclib.protocol import Connection
from grpclib.exceptions import StreamTerminatedError

from dummy_pb2 import DummyRequest, DummyReply

from conn import ClientServer


class PingServiceHandler:
    async def UnaryStream(self, stream):
        await stream.recv_message()
        await stream.send_message(DummyReply(value='ping'))
        await asyncio.sleep(0.1)
        await stream.send_message(DummyReply(value='ping'))

    def __mapping__(self):
        return {
            '/ping.PingService/UnaryStream': grpclib.const.Handler(
                self.UnaryStream,
                grpclib.const.Cardinality.UNARY_STREAM,
                DummyRequest,
                DummyReply,
            ),
        }


class PingServiceStub:

    def __init__(self, channel):
        self.UnaryStream = UnaryStreamMethod(
            channel,
            '/ping.PingService/UnaryStream',
            DummyRequest,
            DummyReply,
        )


@pytest.mark.asyncio
async def test_stream_cancel_by_ping():
    ctx = ClientServer(PingServiceHandler, PingServiceStub,
                       config=Configuration(_keepalive_time=0.01,
                                            _keepalive_timeout=0.04,
                                            _http2_max_pings_without_data=1,
                                            ))

    # should be successful
    async with ctx as (handler, stub):
        await stub.UnaryStream(DummyRequest(value='ping'))
        assert ctx.channel._protocol.connection.last_ping_sent is not None

    # disable ping ack logic to cause a timeout and disconnect
    with patch.object(Connection, 'ping_ack_process') as p:
        p.return_value = None
        with pytest.raises(StreamTerminatedError, match='Connection lost'):
            async with ctx as (handler, stub):
                await stub.UnaryStream(DummyRequest(value='ping'))
