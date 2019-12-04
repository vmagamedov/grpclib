import pytest
import asyncio
import async_timeout

import grpclib.const
import grpclib.server
from grpclib.client import UnaryStreamMethod
from grpclib.exceptions import StreamTerminatedError
from grpclib.config import Configuration

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
async def test_stream_ping():
    ctx = ClientServer(PingServiceHandler, PingServiceStub)
    async with ctx as (handler, stub):
        await stub.UnaryStream(DummyRequest(value='ping'))


@pytest.mark.asyncio
async def test_stream_cancel_by_ping():
    ctx = ClientServer(PingServiceHandler, PingServiceStub,
                       config=Configuration(_keepalive_time=0.01,
                                            _keepalive_timeout=0.04,
                                            _http2_max_pings_without_data=1,
                                            ))
    with pytest.raises(StreamTerminatedError):
        with async_timeout.timeout(5):
            async with ctx as (handler, stub):
                await stub.UnaryStream(DummyRequest(value='ping'))
