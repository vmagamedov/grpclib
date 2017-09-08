import abc
import struct


CONTENT_TYPE = 'application/grpc+proto'
CONTENT_TYPES = {'application/grpc', 'application/grpc+proto'}


async def recv_message(stream, message_type):
    meta = await stream.recv_data(5)
    if not meta:
        return

    compressed_flag = struct.unpack('?', meta[:1])[0]
    if compressed_flag:
        raise NotImplementedError('Compression not implemented')

    message_len = struct.unpack('>I', meta[1:])[0]
    message_bin = await stream.recv_data(message_len)
    assert len(message_bin) == message_len, \
        '{} != {}'.format(len(message_bin), message_len)
    message = message_type.FromString(message_bin)
    return message


async def send_message(stream, message, message_type, *, end=False):
    assert isinstance(message, message_type), type(message)
    reply_bin = message.SerializeToString()
    reply_data = (struct.pack('?', False)
                  + struct.pack('>I', len(reply_bin))
                  + reply_bin)
    await stream.send_data(reply_data, end_stream=end)


class StreamIterator(abc.ABC):

    @abc.abstractmethod
    async def recv_message(self):
        pass

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.recv_message()
        if message is None:
            raise StopAsyncIteration()
        else:
            return message
