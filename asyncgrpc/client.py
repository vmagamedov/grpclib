import struct

from functools import partial
from collections import namedtuple

from h2.config import H2Configuration
from multidict import MultiDict

from .protocol import H2Protocol, WrapProtocolMixin, NoHandler


Method = namedtuple('Method', 'name, request_type, reply_type')

_CONTENT_TYPES = {'application/grpc', 'application/grpc+proto'}


class _Protocol(WrapProtocolMixin, H2Protocol):
    pass


class Channel:

    def __init__(self, host='127.0.0.1', port=50051, *, loop):
        self._host = host
        self._port = port
        self._loop = loop

        self._config = H2Configuration(client_side=True,
                                       header_encoding='utf-8')
        self._authority = '{}:{}'.format(self._host, self._port)
        self._protocol = None

    def _protocol_factory(self):
        return _Protocol(self, NoHandler(), self._config, loop=self._loop)

    async def _ensure_connected(self):
        if self._protocol is None:
            _, self._protocol = await self._loop.create_connection(
                self._protocol_factory, self._host, self._port
            )
        return self._protocol

    def __connection_made__(self, transport):
        pass

    def __connection_lost__(self, exc):
        self._protocol = None

    async def unary_unary(self, method, request, timeout=None, metadata=None,
                          credentials=None):
        assert isinstance(request, method.request_type), \
            '{!r} is not {!r}'.format(type(request), method.request_type)

        request_bin = request.SerializeToString()
        request_data = (struct.pack('?', False)
                        + struct.pack('>I', len(request_bin))
                        + request_bin)

        protocol = await self._ensure_connected()
        stream = await protocol.processor.create_stream()

        await stream.send_headers([
            (':scheme', 'http'),
            (':authority', self._authority),
            (':method', 'POST'),
            (':path', method.name),
            ('user-agent', 'grpc-python'),
            ('content-type', 'application/grpc+proto'),
            ('te', 'trailers'),
        ])

        await stream.send_data(request_data, end_stream=True)

        headers = MultiDict(await stream.recv_headers())
        assert headers[':status'] == '200', headers[':status']
        assert headers['content-type'] in _CONTENT_TYPES, \
            headers['content-type']

        reply_data = await stream.recv_data()
        compressed_flag = struct.unpack('?', reply_data[0:1])[0]
        if compressed_flag:
            raise NotImplementedError('Compression not implemented')

        reply_len = struct.unpack('>I', reply_data[1:5])[0]
        reply_bin = reply_data[5:]
        assert len(reply_bin) == reply_len, \
            '{} != {}'.format(len(reply_bin), reply_len)

        reply_msg = method.reply_type.FromString(reply_bin)

        # TODO: handle trailers
        return reply_msg

    def close(self):
        self._protocol.processor.close()


class CallDescriptor:

    def __init__(self, method):
        self.method = method
        _, _, self.method_name = method.name.split('/')

    def __bind__(self, channel, method):
        raise NotImplementedError

    def __get__(self, instance, owner):
        if instance is None:
            return self
        method = self.__bind__(instance.channel, self.method)
        instance.__dict__[self.method_name] = method
        return method


class UnaryUnaryCall(CallDescriptor):

    def __bind__(self, channel, method):
        return partial(channel.unary_unary, method)
