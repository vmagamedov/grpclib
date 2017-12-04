import pytest
import struct
import asyncio
import collections

from h2.config import H2Configuration
from h2.settings import SettingCodes
from h2.connection import H2Connection

from grpclib.const import Status
from grpclib.stream import CONTENT_TYPE
from grpclib.client import Stream, Handler
from grpclib.protocol import H2Protocol
from grpclib.metadata import Request
from grpclib.exceptions import GRPCError

from stubs import TransportStub
from bombed_pb2 import SavoysRequest, SavoysReply


@pytest.fixture(name='broken_stream')
def _broken_stream():

    class BrokenChannel:
        def __connect__(self):
            raise IOError('Intentionally broken connection')

    request = Request('POST', 'http', '/foo/bar', authority='test.com')
    return Stream(BrokenChannel(), request, SavoysRequest, SavoysReply)


def encode_message(message):
    message_bin = message.SerializeToString()
    header = struct.pack('?', False) + struct.pack('>I', len(message_bin))
    return header + message_bin


class ServerStub:

    def __init__(self, protocol):
        self.connection = H2Connection(H2Configuration(client_side=False,
                                                       header_encoding='utf-8'))
        self._transport = TransportStub(self.connection)

        self._protocol = protocol
        self._protocol.connection_made(self._transport)

    def events(self):
        return self._transport.events()

    def flush(self):
        self._protocol.data_received(self.connection.data_to_send())


class ChannelStub:

    def __init__(self, protocol):
        self.__protocol__ = protocol

    async def __connect__(self):
        return self.__protocol__


Stub = collections.namedtuple('Stub', 'stream, server, channel')


@pytest.fixture(name='stub')
def _stub(loop):
    protocol = H2Protocol(Handler(),
                          H2Configuration(header_encoding='utf-8'),
                          loop=loop)
    channel = ChannelStub(protocol)
    request = Request('POST', 'http', '/foo/bar', authority='test.com')
    stream = Stream(channel, request, SavoysRequest, SavoysReply)
    server = ServerStub(protocol)
    return Stub(stream, server, channel)


@pytest.mark.asyncio
async def test_unary_unary(stub):
    async with stub.stream:
        await stub.stream.send_message(SavoysRequest(kyler='bhatta'),
                                       end=True)

        events = stub.server.events()
        stream_id = events[-1].stream_id

        stub.server.connection.send_headers(
            stream_id,
            [(':status', '200'), ('content-type', CONTENT_TYPE)],
        )
        stub.server.connection.send_data(
            stream_id,
            encode_message(SavoysReply(benito='giselle')),
        )
        stub.server.connection.send_headers(
            stream_id,
            [('grpc-status', str(Status.OK.value))],
            end_stream=True,
        )
        stub.server.flush()

        assert await stub.stream.recv_message() == \
            SavoysReply(benito='giselle')


@pytest.mark.asyncio
async def test_no_request(stub):
    async with stub.stream:
        pass


@pytest.mark.asyncio
async def test_connection_error(broken_stream):
    with pytest.raises(IOError) as err:
        async with broken_stream:
            await broken_stream.send_request()
    err.match('Intentionally broken connection')


@pytest.mark.asyncio
async def test_method_unimplemented(stub):
    with pytest.raises(GRPCError) as err:
        async with stub.stream:
            await stub.stream.send_message(SavoysRequest(kyler='bhatta'),
                                           end=True)

            events = stub.server.events()
            stream_id = events[-1].stream_id

            stub.server.connection.send_headers(
                stream_id,
                [(':status', '200'),
                 ('grpc-status', str(Status.UNIMPLEMENTED.value))],
            )
            stub.server.connection.send_data(
                stream_id,
                encode_message(SavoysReply(benito='giselle')),
            )
            stub.server.connection.send_headers(
                stream_id,
                [('grpc-status', str(Status.OK.value))],
                end_stream=True,
            )
            stub.server.flush()

            assert await stub.stream.recv_message()
    err.match('UNIMPLEMENTED')


class ClientError(Exception):
    pass


@pytest.mark.asyncio
async def test_ctx_exit_with_error_and_closed_stream(stub):
    with pytest.raises(ClientError):
        async with stub.stream:
            await stub.stream.send_request()
            events = stub.server.events()
            stub.server.connection.reset_stream(events[-1].stream_id)
            stub.server.flush()
            raise ClientError()


@pytest.mark.asyncio
async def test_outbound_streams_limit(stub, loop):
    stub.server.connection.update_settings({
        SettingCodes.MAX_CONCURRENT_STREAMS: 1,
    })
    stub.server.flush()

    request = Request('POST', 'http', '/foo/bar', authority='test.com')

    async def worker1():
        s1 = Stream(stub.channel, request, SavoysRequest, SavoysReply)
        async with s1:
            await s1.send_message(SavoysRequest(kyler='bhatta'), end=True)
            assert await s1.recv_message() == SavoysReply(benito='giselle')

    async def worker2():
        s2 = Stream(stub.channel, request, SavoysRequest, SavoysReply)
        async with s2:
            await s2.send_message(SavoysRequest(kyler='bhatta'), end=True)
            assert await s2.recv_message() == SavoysReply(benito='giselle')

    def send_response(stream_id):
        stub.server.connection.send_headers(
            stream_id,
            [(':status', '200'), ('content-type', CONTENT_TYPE)],
        )
        stub.server.connection.send_data(
            stream_id,
            encode_message(SavoysReply(benito='giselle')),
        )
        stub.server.connection.send_headers(
            stream_id,
            [('grpc-status', str(Status.OK.value))],
            end_stream=True,
        )
        stub.server.flush()

    w1 = loop.create_task(worker1())
    w2 = loop.create_task(worker2())

    done, pending = await asyncio.wait([w1, w2], loop=loop, timeout=0.001)
    assert not done and pending == {w1, w2}

    send_response(1)
    await asyncio.wait_for(w1, 0.1, loop=loop)

    send_response(3)
    await asyncio.wait_for(w2, 0.1, loop=loop)
