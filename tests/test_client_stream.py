from unittest.mock import Mock

import pytest
import struct

from grpclib.const import Status
from grpclib.stream import CONTENT_TYPE
from grpclib.client import Stream
from grpclib.metadata import Request

from bombed_pb2 import SavoysRequest, SavoysReply
from test_server_stream import H2StreamStub


@pytest.fixture(name='stub')
def _stub(loop):
    return H2StreamStub(loop=loop)


@pytest.fixture(name='stream')
def _stream(stub):
    stream_mock = Mock()
    stream_mock.processor.create_stream.return_value = stub

    class Channel:
        async def __connect__(self):
            return stream_mock

    request = Request('POST', 'http', '/foo/bar', content_type=CONTENT_TYPE)
    return Stream(Channel(), request, SavoysRequest, SavoysReply)


@pytest.fixture(name='broken_stream')
def _broken_stream():

    class BrokenChannel:
        def __connect__(self):
            raise IOError('Intentionally broken connection')

    request = Request('POST', 'http', '/foo/bar', content_type=CONTENT_TYPE)
    return Stream(BrokenChannel(), request, SavoysRequest, SavoysReply)


def encode_message(message):
    message_bin = message.SerializeToString()
    header = struct.pack('?', False) + struct.pack('>I', len(message_bin))
    return header, message_bin


@pytest.mark.asyncio
async def test_unary_unary(stream, stub):
    stub.__headers__.put_nowait([
        (':status', '200'),
        ('content-type', CONTENT_TYPE),
    ])
    stub.__headers__.put_nowait([
        ('grpc-status', str(Status.OK.value)),
    ])
    header, data = encode_message(SavoysReply(benito='giselle'))
    stub.__data__.put_nowait(header)
    stub.__data__.put_nowait(data)
    async with stream:
        await stream.send_message(SavoysRequest(kyler='bhatta'), end=True)
        assert await stream.recv_message() == SavoysReply(benito='giselle')


@pytest.mark.asyncio
async def test_no_request(stream):
    async with stream:
        pass


@pytest.mark.asyncio
async def test_connection_error(broken_stream):
    with pytest.raises(IOError) as err:
        async with broken_stream:
            await broken_stream.send_request()
    err.match('Intentionally broken connection')
