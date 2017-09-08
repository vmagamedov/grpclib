import logging
import asyncio

import h2.config
import async_timeout

from .exc import GRPCError
from .const import Status
from .stream import CONTENT_TYPE, CONTENT_TYPES, send_message, recv_message
from .stream import StreamIterator
from .metadata import Metadata
from .protocol import H2Protocol, AbstractHandler


log = logging.getLogger(__name__)


class Stream(StreamIterator):
    # stream state
    _recv_message_count = 0
    _send_initial_metadata_done = False
    _send_message_count = 0
    _send_trailing_metadata_done = False
    _reset_done = False

    def __init__(self, metadata, stream, recv_type, send_type):
        self.metadata = metadata
        self._stream = stream
        self._recv_type = recv_type
        self._send_type = send_type

    async def recv_message(self):
        message = await recv_message(self._stream, self._recv_type)
        self._recv_message_count += 1
        return message

    async def send_initial_metadata(self):
        assert not self._send_initial_metadata_done, \
            'Method should be called only once'

        await self._stream.send_headers([(':status', '200'),
                                         ('content-type', CONTENT_TYPE)])
        self._send_initial_metadata_done = True

    async def send_message(self, message, *, end=False):
        if not self._send_initial_metadata_done:
            await self.send_initial_metadata()

        await send_message(self._stream, message, self._send_type)
        self._send_message_count += 1

        if end:
            await self.send_trailing_metadata()

    async def send_trailing_metadata(self, *, status=Status.OK,
                                     status_message=None):
        assert not self._send_trailing_metadata_done, \
            'Method should be called only once'

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

    async def reset(self):
        assert not self._reset_done, 'Stream reset is already done'
        await self._stream.reset()  # TODO: specify error code
        self._reset_done = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._send_trailing_metadata_done or self._reset_done:
            return

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
                                              status_message='Empty reply')
        else:
            await self.send_trailing_metadata()


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
