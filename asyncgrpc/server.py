import struct
import asyncio
import weakref

from collections import namedtuple

from multidict import MultiDict

from .protocol import H2Protocol


Method = namedtuple('Method', 'func, request_type, reply_type')


async def unary_unary(proto, stream_id, method):
    # print(request_type, reply_type)

    request_data = await proto.read_stream(stream_id, -1)
    # print('request_bin', request_data)

    compressed_flag = struct.unpack('?', request_data[0:1])[0]
    if compressed_flag:
        raise NotImplementedError('Compression not implemented')

    request_len = struct.unpack('>I', request_data[1:5])[0]
    request_bin = request_data[5:]
    assert len(request_bin) == request_len, \
        '{} != {}'.format(len(request_bin), request_len)
    request_msg = method.request_type.FromString(request_bin)

    reply_msg = await method.func(request_msg)
    assert isinstance(reply_msg, method.reply_type), type(reply_msg)

    reply_bin = reply_msg.SerializeToString()
    reply_data = (struct.pack('?', False)
                  + struct.pack('>I', len(reply_bin))
                  + reply_bin)
    await proto.send_data(stream_id, reply_data)


async def request_handler(proto, stream_id, headers, mapping):
    h2_method = headers[':method']
    assert h2_method == 'POST', h2_method

    method = mapping.get(headers[':path'])
    assert method is not None, headers[':path']

    await proto.send_headers(stream_id,
                             {':status': '200',
                              'content-type': 'application/grpc+proto'})

    await unary_unary(proto, stream_id, method)

    await proto.send_headers(stream_id,
                             {'grpc-status': '0'},
                             end_stream=True)


async def connection_handler(proto, mapping, *, loop):
    tasks = {}
    try:
        while True:
            stream_id, headers = await proto.recv_request()
            tasks[stream_id] = loop.create_task(
                request_handler(proto, stream_id, MultiDict(headers), mapping)
            )
    except asyncio.CancelledError:
        for task in tasks.values():
            task.cancel()


class _Server(asyncio.AbstractServer):

    def __init__(self, server, protocols):
        self._server = server
        self._protocols = protocols

    def close(self):
        self._server.close()

    async def wait_closed(self):
        for proto in self._protocols:
            await proto.shutdown()
        await self._server.wait_closed()


async def create_server(mapping, host='127.0.0.1', port=50051, *, loop):
    protocols = weakref.WeakSet()

    def protocol_factory():
        proto = H2Protocol(connection_handler, mapping, False, loop=loop)
        protocols.add(proto)
        return proto

    server = await loop.create_server(protocol_factory, host, port)
    return _Server(server, protocols)
