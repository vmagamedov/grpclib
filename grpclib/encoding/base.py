import abc

from typing import Any


GRPC_CONTENT_TYPE = 'application/grpc'


class CodecBase(abc.ABC):

    @property
    @abc.abstractmethod
    def __content_subtype__(self) -> str:
        pass

    @abc.abstractmethod
    def encode(self, message: Any, message_type: Any) -> bytes:
        pass

    @abc.abstractmethod
    def decode(self, data: bytes, message_type: Any) -> Any:
        pass
