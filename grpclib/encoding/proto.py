from .base import CodecBase


class ProtoCodec(CodecBase):
    __content_subtype__ = 'proto'

    def encode(self, message, message_type):
        assert isinstance(message, message_type), type(message)
        return message.SerializeToString()

    def decode(self, data, message_type):
        return message_type.FromString(data)
