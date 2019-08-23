import pytest

from google.rpc.error_details_pb2 import Help

from grpclib.const import Status
from grpclib.testing import ChannelFor
from grpclib.exceptions import GRPCError
from grpclib.encoding.proto import ProtoCodec, ProtoStatusDetailsCodec

from dummy_pb2 import DummyRequest
from dummy_grpc import DummyServiceStub
from test_functional import DummyService


class ServiceType1(DummyService):
    async def UnaryUnary(self, stream):
        await stream.send_trailing_metadata(
            status=Status.DATA_LOSS,
            status_message='Some data loss occurred',
            status_details=[
                Help(links=[Help.Link(url='https://example.com')])
            ],
        )


class ServiceType2(DummyService):
    async def UnaryUnary(self, stream):
        raise GRPCError(
            Status.DATA_LOSS,
            'Some data loss occurred',
            [Help(links=[Help.Link(url='https://example.com')])],
        )


@pytest.mark.asyncio
@pytest.mark.parametrize('svc_type', [ServiceType1, ServiceType2])
async def test_send_trailing_metadata(loop, svc_type):
    async with ChannelFor(
        [svc_type()],
        codec=ProtoCodec(),
        status_details_codec=ProtoStatusDetailsCodec(),
    ) as channel:
        stub = DummyServiceStub(channel)
        with pytest.raises(GRPCError) as error:
            await stub.UnaryUnary(DummyRequest(value='ping'))
    assert error.value.status is Status.DATA_LOSS
    assert error.value.message == 'Some data loss occurred'
    assert error.value.details == [
        Help(links=[Help.Link(url='https://example.com')]),
    ]
