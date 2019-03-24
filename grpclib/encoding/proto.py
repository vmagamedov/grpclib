from .base import CodecBase
from typing import Type, TypeVar
from google.protobuf.message import Message

_T = TypeVar("_T", bound=Message)


class ProtoCodec(CodecBase):
    __content_subtype__ = 'proto'

    def encode(self, message: _T, message_type: Type[_T]) -> bytes:
        assert isinstance(message, message_type), type(message)
        return message.SerializeToString()

    def decode(self, data: bytes, message_type: Type[_T]) -> _T:
        return message_type.FromString(data)  # type: ignore
