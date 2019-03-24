import abc
from typing import Type, TypeVar
from google.protobuf.message import Message


_T = TypeVar("_T", bound=Message)
GRPC_CONTENT_TYPE = 'application/grpc'


class CodecBase(abc.ABC):

    @property
    @abc.abstractmethod
    def __content_subtype__(self) -> str:
        pass

    @abc.abstractmethod
    def encode(self, message: _T, message_type: Type[_T]) -> bytes:
        pass

    @abc.abstractmethod
    def decode(self, data: bytes, message_type: Type[_T]) -> _T:
        pass
