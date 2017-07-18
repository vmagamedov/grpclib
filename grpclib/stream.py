import abc
import struct

CONTENT_TYPE = 'application/grpc+proto'
CONTENT_TYPES = {'application/grpc', 'application/grpc+proto'}


class Stream(abc.ABC):
    _stream = None

    def __init__(self, send_type, recv_type):
        self._send_type = send_type
        self._recv_type = recv_type

    async def __aenter__(self):
        return self

    @abc.abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    async def recv(self):
        meta = await self._stream.recv_data(5)
        if not meta:
            return

        compressed_flag = struct.unpack('?', meta[:1])[0]
        if compressed_flag:
            raise NotImplementedError('Compression not implemented')

        message_len = struct.unpack('>I', meta[1:])[0]
        message_bin = await self._stream.recv_data(message_len)
        assert len(message_bin) == message_len, \
            '{} != {}'.format(len(message_bin), message_len)
        message = self._recv_type.FromString(message_bin)
        return message

    async def send(self, message, end=False):
        assert isinstance(message, self._send_type)
        reply_bin = message.SerializeToString()
        reply_data = (struct.pack('?', False)
                      + struct.pack('>I', len(reply_bin))
                      + reply_bin)
        await self._stream.send_data(reply_data, end_stream=end)

    @abc.abstractmethod
    async def end(self):
        pass

    async def reset(self):
        await self._stream.reset()  # TODO: specify error code

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.recv()
        if message is None:
            raise StopAsyncIteration()
        else:
            return message
