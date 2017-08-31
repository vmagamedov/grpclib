import logging
import asyncio

import h2.config
import async_timeout

from .enum import Status
from .stream import CONTENT_TYPE, CONTENT_TYPES, Stream as _Stream
from .metadata import Metadata
from .protocol import H2Protocol, AbstractHandler


log = logging.getLogger(__name__)


class GRPCError(Exception):

    def __init__(self, status, message=None):
        super().__init__(message)
        self.status = status
        self.message = message


class Stream(_Stream):
    _headers_sent = False
    _trailers_sent = False
    _data_sent = False
    _ended = False

    def __init__(self, metadata, stream, recv_type, send_type):
        self.metadata = metadata
        self._stream = stream
        self._recv_type = recv_type
        self._send_type = send_type

    async def _send_trailers(self, trailers):
        assert not self._trailers_sent
        if not self._headers_sent:
            trailers = [(':status', '200')] + trailers
        await self._stream.send_headers(trailers, end_stream=True)
        self._headers_sent = True
        self._trailers_sent = True

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._ended:
            return

        if exc_type or exc_val or exc_tb:
            if isinstance(exc_val, GRPCError):
                status, message = exc_val.status, exc_val.message
            else:
                status, message = Status.UNKNOWN, 'Internal Server Error'
            headers = [('grpc-status', str(status.value))]
            if message is not None:
                headers.append(('grpc-message', message))

        elif not self._data_sent:
            headers = [('grpc-status', str(Status.UNKNOWN.value)),
                       ('grpc-message', 'Empty reply')]

        else:
            headers = [('grpc-status', str(Status.OK.value))]

        await self._send_trailers(headers)
        # to suppress exception propagation
        return True

    async def send(self, message, end=False):
        if not self._headers_sent:
            await self._stream.send_headers([(':status', '200'),
                                             ('content-type', CONTENT_TYPE)])
            self._headers_sent = True

        await super().send(message)
        self._data_sent = True

        if end:
            await self.end()

    async def end(self):
        assert not self._ended
        await self._send_trailers([('grpc-status', str(Status.OK.value))])
        self._ended = True


async def request_handler(mapping, _stream, headers):
    headers_map = dict(headers)
    h2_method = headers_map[':method']
    h2_path = headers_map[':path']
    h2_content_type = headers_map['content-type']

    metadata = Metadata.from_headers(headers)
    if metadata.deadline is not None:
        request_timeout = metadata.deadline.time_remaining()
    else:
        request_timeout = None

    method = mapping.get(h2_path)

    assert h2_method == 'POST', h2_method
    assert method is not None, h2_path
    assert h2_content_type in CONTENT_TYPES, h2_content_type

    async with Stream(metadata, _stream, method.request_type,
                      method.reply_type) as stream:
        timeout_cm = None
        try:
            with async_timeout.timeout(request_timeout) as timeout_cm:
                await method.func(stream)
        except asyncio.TimeoutError:
            if timeout_cm and timeout_cm.expired:
                raise GRPCError(Status.DEADLINE_EXCEEDED)
            else:
                log.exception('Server error')
                raise
        except Exception:
            log.exception('Server error')
            raise


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
            await asyncio.wait(self._cancelled, loop=self.loop)


class Server(asyncio.AbstractServer):

    def __init__(self, handlers, *, loop):
        mapping = {}
        for handler in handlers:
            mapping.update(handler.__mapping__())

        self._mapping = mapping
        self._loop = loop
        self._config = h2.config.H2Configuration(
            client_side=False,
            header_encoding='utf-8',
        )

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
            await asyncio.wait({h.wait_closed() for h in self._handlers},
                               loop=self._loop)
