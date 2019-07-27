import pytest
from google.protobuf.empty_pb2 import Empty

from grpclib.const import Handler, Cardinality, Status
from grpclib.client import UnaryUnaryMethod, StreamUnaryMethod
from grpclib.client import StreamStreamMethod
from grpclib.testing import ChannelFor
from grpclib.exceptions import GRPCError


@pytest.mark.asyncio
@pytest.mark.parametrize('cardinality, method_cls, method_arg', [
    (Cardinality.UNARY_UNARY, UnaryUnaryMethod, Empty()),
    (Cardinality.STREAM_UNARY, StreamUnaryMethod, [Empty()]),
])
async def test_unary_reply_error(cardinality, method_cls, method_arg):
    class Service:
        async def Case(self, stream):
            await stream.send_initial_metadata()
            await stream.send_trailing_metadata(status=Status.PERMISSION_DENIED)

        def __mapping__(self):
            return {
                '/test.Test/Case': Handler(
                    self.Case,
                    cardinality,
                    Empty,
                    Empty,
                )
            }

    async with ChannelFor([Service()]) as channel:
        method = method_cls(channel, '/test.Test/Case', Empty, Empty)
        with pytest.raises(GRPCError) as err:
            await method(method_arg)
        assert err.value.status is Status.PERMISSION_DENIED


@pytest.mark.asyncio
@pytest.mark.parametrize('cardinality, method_cls, method_res', [
    (Cardinality.STREAM_UNARY, StreamUnaryMethod, Empty()),
    (Cardinality.STREAM_STREAM, StreamStreamMethod, [Empty()]),
])
async def test_empty_streaming_request(cardinality, method_cls, method_res):
    class Service:
        async def Case(self, stream):
            await stream.send_message(Empty())

        def __mapping__(self):
            return {
                '/test.Test/Case': Handler(
                    self.Case,
                    cardinality,
                    Empty,
                    Empty,
                )
            }

    async with ChannelFor([Service()]) as channel:
        method = method_cls(channel, '/test.Test/Case', Empty, Empty)
        assert await method([]) == method_res
