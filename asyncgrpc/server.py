import struct
from asyncio import AbstractServer, wait

from collections import namedtuple, defaultdict

from h2.config import H2Configuration
from multidict import CIMultiDict

from .protocol import H2Protocol, WrapProtocolMixin


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
    headers = CIMultiDict(headers)

    h2_method = headers[':method']
    assert h2_method == 'POST', h2_method

    method = mapping.get(headers[':path'])
    assert method is not None, headers[':path']

    await stream.send_headers([(':status', '200'),
                               ('content-type', 'application/grpc+proto')])

    await unary_unary(stream, method)

    await stream.send_headers([('grpc-status', '0')],
                              end_stream=True)


class _Protocol(WrapProtocolMixin, H2Protocol):
    pass


class Server(AbstractServer):

    def __init__(self, handlers, *, loop):
        mapping = {}
        for handler in handlers:
            mapping.update(handler.__mapping__())

        self._mapping = mapping
        self._loop = loop
        self._config = H2Configuration(client_side=False,
                                       header_encoding='utf-8')

        self._tasks = defaultdict(set)
        self._cancelled = set()
        self._tcp_server = None

    async def _stream_handler(self, stream, headers):
        await request_handler(self._mapping, stream, headers)

    async def _connection_handler(self, protocol):
        tasks = self._tasks[protocol]
        while True:
            request = await protocol.processor.requests.get()

            # cleanup done tasks, TODO: do not perform too frequently
            tasks = {t for t in tasks if not t.done()}

            tasks.add(self._loop.create_task(
                self._stream_handler(request.stream, request.headers)
            ))

    def __connection_made__(self, protocol):
        self._tasks[protocol].add(self._loop.create_task(
            self._connection_handler(protocol)
        ))

    def __connection_lost__(self, protocol):
        tasks = self._tasks.pop(protocol)
        for task in tasks:
            task.cancel()

        # cleanup cancelled tasks, TODO: do not perform too frequently
        self._cancelled = {t for t in self._cancelled if not t.done()}
        self._cancelled.update(tasks)

    def _protocol_factory(self):
        return _Protocol(self, self._config, loop=self._loop)

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
        # TODO: cancel all tasks here or rely on `connection_lost`?

    async def wait_closed(self):
        if self._tcp_server is None:
            raise RuntimeError('Server is not started')
        await self._tcp_server.wait_closed()
        await wait(self._cancelled, loop=self._loop)
        assert not self._tasks
