import abc
import socket
import logging
import asyncio
import warnings

import h2.config
import h2.exceptions

from .utils import DeadlineWrapper
from .const import Status
from .stream import CONTENT_TYPE, CONTENT_TYPES, send_message, recv_message
from .stream import StreamIterator
from .metadata import Metadata, Deadline
from .protocol import H2Protocol, AbstractHandler
from .exceptions import GRPCError, ProtocolError


log = logging.getLogger(__name__)


class Stream(StreamIterator):
    """
    Represents gRPC method call – HTTP/2 request/stream, and everything you
    need to communicate with client in order to handle this request.

    As you can see, every method handler accepts single positional argument -
    stream:

    .. code-block:: python

        async def MakeLatte(self, stream: grpclib.server.Stream):
            task: cafe_pb2.LatteOrder = await stream.recv_message()
            ...
            await stream.send_message(empty_pb2.Empty())

    This is true for every gRPC method type.
    """
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
        """Coroutine to receive incoming message from the client.

        If client sends UNARY request, then you can call this coroutine
        only once. If client sends STREAM request, then you should call this
        coroutine several times, until it returns None. To simplify your code
        in this case, :py:class:`Stream` class implements async iteration
        protocol, so you can use it like this:

        .. code-block:: python

            async for massage in stream:
                do_smth_with(message)

        or even like this:

        .. code-block:: python

            messages = [msg async for msg in stream]

        HTTP/2 has flow control mechanism, so server will acknowledge received
        DATA frames as a message only after user consumes this coroutine.

        :returns: protobuf message
        """
        return await recv_message(self._stream, self._recv_type)

    async def send_initial_metadata(self):
        """Coroutine to send headers with initial metadata to the client.

        In gRPC you can send initial metadata as soon as possible, because
        gRPC doesn't use `:status` pseudo header to indicate success or failure
        of the current request. gRPC uses trailers for this purpose, and
        trailers are sent during :py:meth:`send_trailing_metadata` call, which
        should be called in the end.

        .. note:: This coroutine will be called implicitly during first
            :py:meth:`send_message` coroutine call, if not called before
            explicitly.
        """
        if self._send_initial_metadata_done:
            raise ProtocolError('Initial metadata was already sent')

        await self._stream.send_headers([(':status', '200'),
                                         ('content-type', CONTENT_TYPE)])
        self._send_initial_metadata_done = True

    async def send_message(self, message, **kwargs):
        """Coroutine to send message to the client.

        If server sends UNARY response, then you should call this coroutine only
        once. If server sends STREAM response, then you can call this coroutine
        as many times as you need.

        :param message: protobuf message object
        """
        if 'end' in kwargs:
            warnings.warn('"end" argument is deprecated, use '
                          '"stream.send_trailing_metadata" explicitly',
                          stacklevel=2)

        end = kwargs.pop('end', False)
        assert not kwargs, kwargs

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
        """Coroutine to send trailers with trailing metadata to the client.

        This coroutine allows sending trailers-only responses, in case of some
        failure conditions during handling current request, i.e. when
        ``status is not OK``.

        .. note:: This coroutine will be called implicitly at exit from
            request handler, with appropriate status code, if not called
            explicitly during handler execution.

        :param status: resulting status of this coroutine call
        :param status_message: description for a status
        """
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

        if status != Status.OK:
            self._stream.reset_nowait()

    async def cancel(self):
        """Coroutine to cancel this request/stream.

        Server will send RST_STREAM frame to the client, so it will be
        explicitly informed that there is nothing to expect from the server
        regarding this request/stream.
        """
        if self._cancel_done:
            raise ProtocolError('Stream was already cancelled')

        await self._stream.reset()  # TODO: specify error code
        self._cancel_done = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if (
            self._send_trailing_metadata_done
            or self._cancel_done
            or self._stream._transport.is_closing()
        ):
            # to suppress exception propagation
            return True

        if exc_val is not None:
            if isinstance(exc_val, GRPCError):
                status = exc_val.status
                status_message = exc_val.message
            elif isinstance(exc_val, Exception):
                status = Status.UNKNOWN
                status_message = 'Internal Server Error'
            else:
                # propagate exception
                return
        elif not self._send_message_count:
            status = Status.UNKNOWN
            status_message = 'Empty response'
        else:
            status = Status.OK
            status_message = None

        try:
            await self.send_trailing_metadata(status=status,
                                              status_message=status_message)
        except h2.exceptions.StreamClosedError:
            pass

        # to suppress exception propagation
        return True


async def request_handler(mapping, _stream, headers, release_stream):
    try:
        headers_map = dict(headers)

        h2_method = headers_map[':method']
        if h2_method != 'POST':
            await _stream.send_headers([
                (':status', '405'),
            ], end_stream=True)
            _stream.reset_nowait()
            return

        h2_content_type = headers_map.get('content-type')
        if h2_content_type is None:
            await _stream.send_headers([
                (':status', '415'),
                ('grpc-status', str(Status.UNKNOWN.value)),
                ('grpc-message', 'Missing content-type header'),
            ], end_stream=True)
            _stream.reset_nowait()
            return
        elif h2_content_type not in CONTENT_TYPES:
            await _stream.send_headers([
                (':status', '415'),
                ('grpc-status', str(Status.UNKNOWN.value)),
                ('grpc-message', 'Unacceptable content-type header'),
            ], end_stream=True)
            _stream.reset_nowait()
            return

        h2_path = headers_map[':path']
        method = mapping.get(h2_path)
        if method is None:
            await _stream.send_headers([
                (':status', '200'),
                ('grpc-status', str(Status.UNIMPLEMENTED.value)),
                ('grpc-message', 'Method not found'),
            ], end_stream=True)
            _stream.reset_nowait()
            return

        metadata = Metadata.from_headers(headers)
        try:
            deadline = Deadline.from_metadata(metadata)
        except ValueError:
            await _stream.send_headers([
                (':status', '200'),
                ('grpc-status', str(Status.UNKNOWN.value)),
                ('grpc-message', 'Invalid grpc-timeout header'),
            ], end_stream=True)
            _stream.reset_nowait()
            return

        async with Stream(_stream, method.cardinality,
                          method.request_type, method.reply_type,
                          metadata=metadata, deadline=deadline) as stream:
            deadline_wrapper = None
            try:
                if deadline:
                    deadline_wrapper = DeadlineWrapper()
                    with deadline_wrapper.start(deadline):
                        with deadline_wrapper:
                            await method.func(stream)
                else:
                    await method.func(stream)
            except asyncio.TimeoutError:
                if deadline_wrapper and deadline_wrapper.cancelled:
                    log.exception('Deadline exceeded')
                    raise GRPCError(Status.DEADLINE_EXCEEDED)
                else:
                    log.exception('Timeout occurred')
                    raise
            except asyncio.CancelledError:
                log.exception('Request was cancelled')
                raise
            except Exception:
                log.exception('Application error')
                raise
    except Exception:
        log.exception('Server error')
    finally:
        release_stream()


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

    def accept(self, stream, headers, release_stream):
        self.__gc_step__()
        self._tasks[stream] = self.loop.create_task(
            request_handler(self.mapping, stream, headers, release_stream)
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
    """
    HTTP/2 server, which uses gRPC service handlers to handle requests.

    Handler is a subclass of the abstract base class, which was generated
    from .proto file:

    .. code-block:: python

        class CoffeeMachine(cafe_grpc.CoffeeMachineBase):

            async def MakeLatte(self, stream):
                task: cafe_pb2.LatteOrder = await stream.recv_message()
                ...
                await stream.send_message(empty_pb2.Empty())

        server = Server([CoffeeMachine()], loop=loop)
    """
    __gc_interval__ = 10

    def __init__(self, handlers, *, loop):
        """
        :param handlers: list of handlers
        :param loop: asyncio-compatible event loop
        """
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

    async def start(self, host=None, port=None, *,
                    family=socket.AF_UNSPEC, flags=socket.AI_PASSIVE,
                    sock=None, backlog=100, ssl=None, reuse_address=None,
                    reuse_port=None):
        """Coroutine to start the server.

        :param host: can be a string, containing IPv4/v6 address or domain name.
            If host is None, server will be bound to all available interfaces.

        :param port: port number.

        :param family: can be set to either :py:data:`python:socket.AF_INET` or
            :py:data:`python:socket.AF_INET6` to force the socket to use IPv4 or
            IPv6. If not set it will be determined from host.

        :param flags: is a bitmask for
            :py:meth:`~python:asyncio.AbstractEventLoop.getaddrinfo`.

        :param sock: sock can optionally be specified in order to use a
            preexisting socket object. If specified, host and port should be
            omitted (must be None).

        :param backlog: is the maximum number of queued connections passed to
            listen().

        :param ssl: can be set to an :py:class:`~python:ssl.SSLContext`
            to enable SSL over the accepted connections.

        :param reuse_address: tells the kernel to reuse a local socket in
            TIME_WAIT state, without waiting for its natural timeout to expire.

        :param reuse_port: tells the kernel to allow this endpoint to be bound
            to the same port as other existing endpoints are bound to,
            so long as they all set this flag when being created.
        """
        if self._tcp_server is not None:
            raise RuntimeError('Server is already started')

        self._tcp_server = await self._loop.create_server(
            self._protocol_factory, host, port,
            family=family, flags=flags, sock=sock, backlog=backlog, ssl=ssl,
            reuse_address=reuse_address, reuse_port=reuse_port
        )

    def close(self):
        """Stops accepting new connections, cancels all currently running
        requests. Request handlers are able to handle `CancelledError` and
        exit properly.
        """
        if self._tcp_server is None:
            raise RuntimeError('Server is not started')
        self._tcp_server.close()
        for handler in self._handlers:
            handler.close()

    async def wait_closed(self):
        """Coroutine to wait until all existing request handlers will exit
        properly.
        """
        if self._tcp_server is None:
            raise RuntimeError('Server is not started')
        await self._tcp_server.wait_closed()
        if self._handlers:
            await asyncio.wait({h.wait_closed() for h in self._handlers},
                               loop=self._loop)
