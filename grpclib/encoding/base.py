import abc


GRPC_CONTENT_TYPE = 'application/grpc'


class CodecBase(abc.ABC):

    @property
    @abc.abstractmethod
    def __content_subtype__(self):
        pass

    @abc.abstractmethod
    def encode(self, message, message_type) -> bytes:
        pass

    @abc.abstractmethod
    def decode(self, data: bytes, message_type):
        pass
