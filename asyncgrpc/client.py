import struct

from functools import partial
from collections import namedtuple

import aioh2

from multidict import MultiDict


Method = namedtuple('Method', 'name, request_type, reply_type')


class Channel:

    def __init__(self, host='127.0.0.1', port=50051, *, loop):
        self.host = host
        self.port = port
        self.loop = loop
        self._authority = '{}:{}'.format(self.host, self.port)

    async def unary_unary(self, method, request, timeout=None, metadata=None,
                          credentials=None):
        assert isinstance(request, method.request_type), \
            '{!r} is not {!r}'.format(type(request), method.request_type)

        request_bin = request.SerializeToString()
        request_data = (struct.pack('?', False)
                        + struct.pack('>I', len(request_bin))
                        + request_bin)

        proto = await aioh2.open_connection(self.host, self.port,
                                            loop=self.loop)

        stream_id = await proto.start_request([
            (':scheme', 'http'),
            (':authority', self._authority),
            (':method', 'POST'),
            (':path', method.name),
            ('user-agent', 'grpc-python asyncgrpc'),
        ])

        await proto.send_data(stream_id, request_data, end_stream=True)

        headers = MultiDict(await proto.recv_response(stream_id))
        assert headers[':status'] == '200', headers[':status']
        assert headers['content-type'] == 'application/grpc+proto', \
            headers['content-type']

        reply_data = await proto.read_stream(stream_id, -1)
        compressed_flag = struct.unpack('?', reply_data[0:1])[0]
        if compressed_flag:
            raise NotImplementedError('Compression not implemented')

        reply_len = struct.unpack('>I', reply_data[1:5])[0]
        reply_bin = reply_data[5:]
        assert len(reply_bin) == reply_len, \
            '{} != {}'.format(len(reply_bin), reply_len)

        reply_msg = method.reply_type.FromString(reply_bin)

        # TODO: proper resources management
        proto._conn.close_connection()

        return reply_msg


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
