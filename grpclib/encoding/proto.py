from typing import Type, TYPE_CHECKING

from .base import CodecBase


if TYPE_CHECKING:
    from .._protocols import IProtoMessage  # noqa


class ProtoCodec(CodecBase):
    __content_subtype__ = 'proto'

    def encode(
        self,
        message: 'IProtoMessage',
        message_type: Type['IProtoMessage'],
    ) -> bytes:
        assert isinstance(message, message_type), type(message)
        return message.SerializeToString()

    def decode(
        self,
        data: bytes,
        message_type: Type['IProtoMessage'],
    ) -> 'IProtoMessage':
        return message_type.FromString(data)
