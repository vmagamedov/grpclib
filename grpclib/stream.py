import abc
import struct

from typing import Type, TypeVar, Optional, AsyncIterator


NOTHING = object()

_SendType = TypeVar('_SendType')
_RecvType = TypeVar('_RecvType')


async def recv_message(stream, codec, message_type: Type[_RecvType]):
    meta = await stream.recv_data(5)
    if not meta:
        return NOTHING

    compressed_flag = struct.unpack('?', meta[:1])[0]
    if compressed_flag:
        raise NotImplementedError('Compression not implemented')

    message_len = struct.unpack('>I', meta[1:])[0]
    message_bin = await stream.recv_data(message_len)
    assert len(message_bin) == message_len, \
        '{} != {}'.format(len(message_bin), message_len)
    message = codec.decode(message_bin, message_type)
    return message


async def send_message(stream, codec, message, message_type: Type[_SendType],
                       *, end=False):
    reply_bin = codec.encode(message, message_type)
    reply_data = (struct.pack('?', False)
                  + struct.pack('>I', len(reply_bin))
                  + reply_bin)
    await stream.send_data(reply_data, end_stream=end)


class StreamIterator(AsyncIterator[_RecvType], metaclass=abc.ABCMeta):

    @abc.abstractmethod
    async def recv_message(self) -> Optional[_RecvType]:
        pass

    def __aiter__(self) -> AsyncIterator[_RecvType]:
        return self

    async def __anext__(self) -> _RecvType:
        message = await self.recv_message()
        if message is None:
            raise StopAsyncIteration()
        else:
            return message
