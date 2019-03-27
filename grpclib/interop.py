from typing import Any

from google.protobuf.message import Message

from .client import Channel, UnaryUnaryMethod, UnaryStreamMethod
from .client import StreamUnaryMethod, StreamStreamMethod


class InteropChannel(Channel):
    """
    A Channel compatible with ``grpcio``-generated stubs

    .. code-block:: python3

        channel = InteropChannel(host, port)
        client = cafe_pb2_grpc.CoffeeMachineStub(channel)

        ...

        request = cafe_pb2.LatteOrder(
            size=cafe_pb2.SMALL,
            temperature=70,
            sugar=3,
        )
        reply: empty_pb2.Empty = await client.MakeLatte(request)

        ...

        channel.close()
    """
    def unary_unary(
        self,
        method: str,
        request_serializer: Any,
        response_deserializer: Any,
    ) -> UnaryUnaryMethod[Any, Any]:
        return UnaryUnaryMethod(self, method, Message,
                                response_deserializer.__self__)

    def unary_stream(
        self,
        method: str,
        request_serializer: Any,
        response_deserializer: Any,
    ) -> UnaryStreamMethod[Any, Any]:
        return UnaryStreamMethod(self, method, Message,
                                 response_deserializer.__self__)

    def stream_unary(
        self,
        method: str,
        request_serializer: Any,
        response_deserializer: Any,
    ) -> StreamUnaryMethod[Any, Any]:
        return StreamUnaryMethod(self, method, Message,
                                 response_deserializer.__self__)

    def stream_stream(
        self,
        method: str,
        request_serializer: Any,
        response_deserializer: Any,
    ) -> StreamStreamMethod[Any, Any]:
        return StreamStreamMethod(self, method, Message,
                                  response_deserializer.__self__)
