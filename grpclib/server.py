import logging

from asyncio import AbstractServer, wait

from h2.config import H2Configuration

from .stream import recv_gen, send
from .protocol import H2Protocol, AbstractHandler


log = logging.getLogger(__name__)


async def request_handler(mapping, stream, headers):
    headers = dict(headers)

    h2_method = headers[':method']
    assert h2_method == 'POST', h2_method

    method = mapping.get(headers[':path'])
    assert method is not None, headers[':path']

    await stream.send_headers([(':status', '200'),
                               ('content-type', 'application/grpc+proto')])

    try:
        if method.cardinality.value.client_streaming:
            request = recv_gen(stream, method.request_type)
        else:
            request, = [r async for r in recv_gen(stream, method.request_type)]

        if method.cardinality.value.server_streaming:
            async for reply_msg in method.func(request, None):
                assert isinstance(reply_msg, method.reply_type), type(reply_msg)
                await send(stream, reply_msg)
        else:
            reply = await method.func(request, None)
            assert isinstance(reply, method.reply_type), type(reply)
            await send(stream, reply)
    except Exception:
        log.exception('Server error')
        await stream.send_headers([('grpc-status', '2')],
                                  end_stream=True)
    else:
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
