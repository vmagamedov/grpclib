import struct

from asyncio import AbstractServer, wait
from collections import namedtuple

from h2.config import H2Configuration

from .protocol import H2Protocol, AbstractHandler

Method = namedtuple('Method', 'func, request_type, reply_type')


async def unary_unary(stream, method):
    # print(request_type, reply_type)

    request_data = await stream.recv_data()
    # print('request_bin', request_data)

    compressed_flag = struct.unpack('?', request_data[0:1])[0]
    if compressed_flag:
        raise NotImplementedError('Compression not implemented')

    request_len = struct.unpack('>I', request_data[1:5])[0]
    request_bin = request_data[5:]
    assert len(request_bin) == request_len, \
        '{} != {}'.format(len(request_bin), request_len)
    request_msg = method.request_type.FromString(request_bin)

    reply_msg = await method.func(request_msg, None)  # FIXME: pass context
    assert isinstance(reply_msg, method.reply_type), type(reply_msg)

    reply_bin = reply_msg.SerializeToString()
    reply_data = (struct.pack('?', False)
                  + struct.pack('>I', len(reply_bin))
                  + reply_bin)
    await stream.send_data(reply_data)


async def request_handler(mapping, stream, headers):
    headers = dict(headers)

    h2_method = headers[':method']
    assert h2_method == 'POST', h2_method

    method = mapping.get(headers[':path'])
    assert method is not None, headers[':path']

    await stream.send_headers([(':status', '200'),
                               ('content-type', 'application/grpc+proto')])

    await unary_unary(stream, method)

    await stream.send_headers([('grpc-status', '0')],
                              end_stream=True)


class Handler(AbstractHandler):

    def __init__(self, mapping, *, loop):
        self.mapping = mapping
        self.loop = loop
        self.tasks = {}
        self._cancelled = set()

    def accept(self, stream, headers):
        self.tasks[stream] = self.loop.create_task(
            request_handler(self.mapping, stream, headers)
        )

    def cancel(self, stream):
        task = self.tasks.pop(stream)
        task.cancel()
        self._cancelled.add(task)

    def close(self):
        for task in self.tasks.values():
            task.cancel()
        self._cancelled.update(self.tasks.values())

    async def wait_closed(self):
        if self._cancelled:
            await wait(self._cancelled, loop=self.loop)


class Server(AbstractServer):

    def __init__(self, handlers, *, loop):
        mapping = {}
        for handler in handlers:
            mapping.update(handler.__mapping__())

        self._mapping = mapping
        self._loop = loop
        self._config = H2Configuration(client_side=False,
                                       header_encoding='utf-8')

        self._tcp_server = None
        self._handlers = set()  # TODO: cleanup

    async def _stream_handler(self, stream, headers):
        await request_handler(self._mapping, stream, headers)

    def _protocol_factory(self):
        handler = Handler(self._mapping, loop=self._loop)
        self._handlers.add(handler)
        return H2Protocol(handler, self._config, loop=self._loop)

    async def start(self, *args, **kwargs):
        if self._tcp_server is not None:
            raise RuntimeError('Server is already started')

        self._tcp_server = await self._loop.create_server(
            self._protocol_factory, *args, **kwargs
        )

    def close(self):
        if self._tcp_server is None:
            raise RuntimeError('Server is not started')
        self._tcp_server.close()
        for handler in self._handlers:
            handler.close()

    async def wait_closed(self):
        if self._tcp_server is None:
            raise RuntimeError('Server is not started')
        await self._tcp_server.wait_closed()
        if self._handlers:
            await wait({h.wait_closed() for h in self._handlers},
                       loop=self._loop)
