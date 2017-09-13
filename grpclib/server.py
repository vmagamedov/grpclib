import abc
import logging
import asyncio

import h2.config
import async_timeout

from .const import Status
from .stream import CONTENT_TYPE, CONTENT_TYPES, send_message, recv_message
from .stream import StreamIterator
from .metadata import Metadata, Deadline
from .protocol import H2Protocol, AbstractHandler
from .exceptions import GRPCError, ProtocolError


log = logging.getLogger(__name__)


class Stream(StreamIterator):
    # stream state
    _send_initial_metadata_done = False
    _send_message_count = 0
    _send_trailing_metadata_done = False
    _cancel_done = False

    def __init__(self, stream, cardinality, recv_type, send_type,
                 *, metadata, deadline=None):
        self._stream = stream
        self._cardinality = cardinality
        self._recv_type = recv_type
        self._send_type = send_type
        self.metadata = metadata
        self.deadline = deadline

    async def recv_message(self):
        return await recv_message(self._stream, self._recv_type)

    async def send_initial_metadata(self):
        if self._send_initial_metadata_done:
            raise ProtocolError('Initial metadata was already sent')

        await self._stream.send_headers([(':status', '200'),
                                         ('content-type', CONTENT_TYPE)])
        self._send_initial_metadata_done = True

    async def send_message(self, message, *, end=False):
        if not self._send_initial_metadata_done:
            await self.send_initial_metadata()

        if not self._cardinality.server_streaming:
            if self._send_message_count:
                raise ProtocolError('Server should send exactly one message '
                                    'in response')

        await send_message(self._stream, message, self._send_type)
        self._send_message_count += 1

        if end:
            await self.send_trailing_metadata()

    async def send_trailing_metadata(self, *, status=Status.OK,
                                     status_message=None):
        if self._send_trailing_metadata_done:
            raise ProtocolError('Trailing metadata was already sent')

        if not self._send_message_count and status is Status.OK:
            raise ProtocolError('{!r} requires non-empty response'
                                .format(status))

        if self._send_initial_metadata_done:
            headers = []
        else:
            # trailers-only response
            headers = [(':status', '200')]

        headers.append(('grpc-status', str(status.value)))
        if status_message is not None:
            headers.append(('grpc-message', status_message))

        await self._stream.send_headers(headers, end_stream=True)
        self._send_trailing_metadata_done = True

    async def cancel(self):
        if self._cancel_done:
            raise ProtocolError('Stream was already cancelled')

        await self._stream.reset()  # TODO: specify error code
        self._cancel_done = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._send_trailing_metadata_done or self._cancel_done:
            # to suppress exception propagation
            return True

        if exc_type or exc_val or exc_tb:
            if isinstance(exc_val, GRPCError):
                status, status_message = exc_val.status, exc_val.message
            else:
                status, status_message = Status.UNKNOWN, 'Internal Server Error'

            await self.send_trailing_metadata(status=status,
                                              status_message=status_message)
            # to suppress exception propagation
            return True
        elif not self._send_message_count:
            await self.send_trailing_metadata(status=Status.UNKNOWN,
                                              status_message='Empty response')
        else:
            await self.send_trailing_metadata()


async def request_handler(mapping, _stream, headers):
    headers_map = dict(headers)
    h2_method = headers_map[':method']
    h2_path = headers_map[':path']
    h2_content_type = headers_map['content-type']

    metadata = Metadata.from_headers(headers)
    deadline = Deadline.from_metadata(metadata)

    method = mapping.get(h2_path)

    assert h2_method == 'POST', h2_method
    assert method is not None, h2_path
    assert h2_content_type in CONTENT_TYPES, h2_content_type

    async with Stream(_stream, method.cardinality,
                      method.request_type, method.reply_type,
                      metadata=metadata, deadline=deadline) as stream:
        timeout = None if deadline is None else deadline.time_remaining()
        timeout_cm = None
        try:
            with async_timeout.timeout(timeout) as timeout_cm:
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


class _GC(abc.ABC):
    _gc_counter = 0

    @property
    @abc.abstractmethod
    def __gc_interval__(self):
        raise NotImplementedError

    @abc.abstractmethod
    def __gc_collect__(self):
        pass

    def __gc_step__(self):
        self._gc_counter += 1
        if not (self._gc_counter % self.__gc_interval__):
            self.__gc_collect__()


class Handler(_GC, AbstractHandler):
    __gc_interval__ = 10

    closing = False

    def __init__(self, mapping, *, loop):
        self.mapping = mapping
        self.loop = loop
        self._tasks = {}
        self._cancelled = set()

    def __gc_collect__(self):
        self._tasks = {s: t for s, t in self._tasks.items()
                       if not t.done()}
        self._cancelled = {t for t in self._cancelled
                           if not t.done()}

    def accept(self, stream, headers):
        self.__gc_step__()
        self._tasks[stream] = self.loop.create_task(
            request_handler(self.mapping, stream, headers)
        )

    def cancel(self, stream):
        task = self._tasks.pop(stream)
        task.cancel()
        self._cancelled.add(task)

    def close(self):
        for task in self._tasks.values():
            task.cancel()
        self._cancelled.update(self._tasks.values())
        self.closing = True

    async def wait_closed(self):
        if self._cancelled:
            await asyncio.wait(self._cancelled, loop=self.loop)

    def check_closed(self):
        self.__gc_collect__()
        return not self._tasks and not self._cancelled


class Server(_GC, asyncio.AbstractServer):
    __gc_interval__ = 10

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
        self._handlers = set()

    def __gc_collect__(self):
        self._handlers = {h for h in self._handlers
                          if not (h.closing and h.check_closed())}

    def _protocol_factory(self):
        self.__gc_step__()
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
