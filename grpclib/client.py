import http
import asyncio
import warnings

try:
    import ssl
except ImportError:
    ssl = None

from h2.config import H2Configuration
from multidict import MultiDict

from .utils import Wrapper, DeadlineWrapper
from .const import Status, Cardinality
from .stream import send_message, recv_message, NOTHING
from .stream import StreamIterator
from .events import _DispatchChannelEvents
from .protocol import H2Protocol, AbstractHandler
from .metadata import Deadline, USER_AGENT, decode_grpc_message, encode_timeout
from .metadata import encode_metadata, decode_metadata
from .exceptions import GRPCError, ProtocolError, StreamTerminatedError
from .encoding.base import GRPC_CONTENT_TYPE
from .encoding.proto import ProtoCodec


_H2_OK = '200'

# https://github.com/grpc/grpc/blob/master/doc/http-grpc-status-mapping.md
_H2_TO_GRPC_STATUS_MAP = {
    # 400
    str(http.HTTPStatus.BAD_REQUEST.value): Status.INTERNAL,
    # 401
    str(http.HTTPStatus.UNAUTHORIZED.value): Status.UNAUTHENTICATED,
    # 403
    str(http.HTTPStatus.FORBIDDEN.value): Status.PERMISSION_DENIED,
    # 404
    str(http.HTTPStatus.NOT_FOUND.value): Status.UNIMPLEMENTED,
    # 502
    str(http.HTTPStatus.BAD_GATEWAY.value): Status.UNAVAILABLE,
    # 503
    str(http.HTTPStatus.SERVICE_UNAVAILABLE.value): Status.UNAVAILABLE,
    # 504
    str(http.HTTPStatus.GATEWAY_TIMEOUT.value): Status.UNAVAILABLE,
    # 429
    str(http.HTTPStatus.TOO_MANY_REQUESTS.value): Status.UNAVAILABLE,
}


class Handler(AbstractHandler):
    connection_lost = False

    def accept(self, stream, headers, release_stream):
        raise NotImplementedError('Client connection can not accept requests')

    def cancel(self, stream):
        pass

    def close(self):
        self.connection_lost = True


class Stream(StreamIterator):
    """
    Represents gRPC method call - HTTP/2 request/stream, and everything you
    need to communicate with server in order to get response.

    In order to work directly with stream, you should
    :py:meth:`ServiceMethod.open` request like this:

    .. code-block:: python3

        request = cafe_pb2.LatteOrder(
            size=cafe_pb2.SMALL,
            temperature=70,
            sugar=3,
        )
        async with client.MakeLatte.open() as stream:
            await stream.send_message(request, end=True)
            reply: empty_pb2.Empty = await stream.recv_message()

    """
    # stream state
    _send_request_done = False
    _send_message_done = False
    _end_done = False
    _recv_initial_metadata_done = False
    _recv_trailing_metadata_done = False
    _cancel_done = False
    _trailers_only = None

    _stream = None
    _release_stream = None

    _wrapper = None
    _wrapper_ctx = None

    #: This property contains initial metadata, received with headers from
    #: the server. It equals to ``None`` initially, and to a multi-dict object
    #: after :py:meth:`recv_initial_metadata` coroutine succeeds.
    initial_metadata = None

    #: This property contains trailing metadata, received with trailers from
    #: the server. It equals to ``None`` initially, and to a multi-dict object
    #: after :py:meth:`recv_trailing_metadata` coroutine succeeds.
    trailing_metadata = None

    def __init__(self, channel, method_name, metadata, cardinality, send_type,
                 recv_type, *, codec, dispatch: _DispatchChannelEvents,
                 deadline=None):
        self._channel = channel
        self._method_name = method_name
        self._metadata = metadata
        self._cardinality = cardinality
        self._send_type = send_type
        self._recv_type = recv_type
        self._codec = codec
        self._dispatch = dispatch
        self._deadline = deadline

    async def send_request(self, *, end=False):
        """Coroutine to send request headers with metadata to the server.

        New HTTP/2 stream will be created during this coroutine call.

        .. note:: This coroutine will be called implicitly during first
            :py:meth:`send_message` coroutine call, if not called before
            explicitly.

        :param end: end outgoing stream if there are no messages to send in
            a streaming request
        """
        if self._send_request_done:
            raise ProtocolError('Request is already sent')

        if end and not self._cardinality.client_streaming:
            raise ProtocolError('Unary request requires a message to be sent '
                                'before ending outgoing stream')

        with self._wrapper:
            protocol = await self._channel.__connect__()
            stream = protocol.processor.connection\
                .create_stream(wrapper=self._wrapper)

            headers = [
                (':method', 'POST'),
                (':scheme', self._channel._scheme),
                (':path', self._method_name),
                (':authority', self._channel._authority),
            ]
            if self._deadline is not None:
                timeout = self._deadline.time_remaining()
                headers.append(('grpc-timeout', encode_timeout(timeout)))
            content_type = (GRPC_CONTENT_TYPE
                            + '+' + self._codec.__content_subtype__)
            headers.extend((
                ('te', 'trailers'),
                ('content-type', content_type),
                ('user-agent', USER_AGENT),
            ))
            metadata, = await self._dispatch.send_request(
                self._metadata,
                method_name=self._method_name,
                deadline=self._deadline,
                content_type=content_type,
            )
            headers.extend(encode_metadata(metadata))
            release_stream = await stream.send_request(
                headers, end_stream=end, _processor=protocol.processor,
            )
            self._stream = stream
            self._release_stream = release_stream
            self._send_request_done = True
            if end:
                self._end_done = True

    async def send_message(self, message, *, end=False):
        """Coroutine to send message to the server.

        If client sends UNARY request, then you should call this coroutine only
        once. If client sends STREAM request, then you can call this coroutine
        as many times as you need.

        .. warning:: It is important to finally end stream from the client-side
            when you finished sending messages.

        You can do this in two ways:

        - specify ``end=True`` argument while sending last message - and last
          DATA frame will include END_STREAM flag;
        - call :py:meth:`end` coroutine after sending last message - and extra
          HEADERS frame with END_STREAM flag will be sent.

        First approach is preferred, because it doesn't require sending
        additional HTTP/2 frame.
        """
        if not self._send_request_done:
            await self.send_request()

        end_stream = end
        if not self._cardinality.client_streaming:
            if self._send_message_done:
                raise ProtocolError('Message was already sent')
            else:
                end_stream = True

        if self._end_done:
            raise ProtocolError('Stream is ended')

        with self._wrapper:
            message, = await self._dispatch.send_message(message)
            await send_message(self._stream, self._codec, message,
                               self._send_type, end=end_stream)
            self._send_message_done = True
            if end:
                self._end_done = True

    async def end(self):
        """Coroutine to end stream from the client-side.

        It should be used to finally end stream from the client-side when we're
        finished sending messages to the server and stream wasn't closed with
        last DATA frame. See :py:meth:`send_message` for more details.

        HTTP/2 stream will have half-closed (local) state after this coroutine
        call.
        """
        if not self._send_request_done:
            raise ProtocolError('Request was not sent')

        if self._end_done:
            raise ProtocolError('Stream was already ended')

        if not self._cardinality.client_streaming:
            if not self._send_message_done:
                raise ProtocolError('Unary request requires a single message '
                                    'to be sent')
            else:
                # `send_message` must already ended stream
                self._end_done = True
                return
        else:
            await self._stream.end()
            self._end_done = True

    def _raise_for_status(self, headers_map):
        status = headers_map[':status']
        if status is not None and status != _H2_OK:
            grpc_status = _H2_TO_GRPC_STATUS_MAP.get(status, Status.UNKNOWN)
            raise GRPCError(grpc_status,
                            'Received :status = {!r}'.format(status))

    def _raise_for_content_type(self, headers_map):
        content_type = headers_map.get('content-type')
        if content_type is None:
            raise GRPCError(Status.UNKNOWN,
                            'Missing content-type header')

        base_content_type, _, sub_type = content_type.partition('+')
        sub_type = sub_type or ProtoCodec.__content_subtype__
        if (
                base_content_type != GRPC_CONTENT_TYPE
                or sub_type != self._codec.__content_subtype__
        ):
            raise GRPCError(Status.UNKNOWN,
                            'Invalid content-type: {!r}'
                            .format(content_type))

    def _raise_for_grpc_status(self, headers_map):
        grpc_status = headers_map.get('grpc-status')
        if grpc_status is None:
            raise GRPCError(Status.UNKNOWN, 'Missing grpc-status header')
        try:
            grpc_status_enum = Status(int(grpc_status))
        except ValueError:
            raise GRPCError(Status.UNKNOWN,
                            'Invalid grpc-status: {!r}'
                            .format(grpc_status))
        else:
            if grpc_status_enum is not Status.OK:
                status_message = headers_map.get('grpc-message')
                if status_message is not None:
                    status_message = decode_grpc_message(status_message)
                raise GRPCError(grpc_status_enum, status_message)

    async def recv_initial_metadata(self):
        """Coroutine to wait for headers with initial metadata from the server.

        .. note:: This coroutine will be called implicitly during first
            :py:meth:`recv_message` coroutine call, if not called before
            explicitly.

        May raise :py:class:`~grpclib.exceptions.GRPCError` if server returned
        non-:py:attr:`Status.OK <grpclib.const.Status.OK>` in trailers-only
        response.

        When this coroutine finishes, you can access received initial metadata
        by using :py:attr:`initial_metadata` attribute.
        """
        if not self._send_request_done:
            raise ProtocolError('Request was not sent yet')

        if self._recv_initial_metadata_done:
            raise ProtocolError('Initial metadata was already received')

        try:
            with self._wrapper:
                headers = await self._stream.recv_headers()
                self._recv_initial_metadata_done = True
                headers_map = dict(headers)
                self._raise_for_status(headers_map)
                self._raise_for_content_type(headers_map)
                if 'grpc-status' in headers_map:  # trailers-only response
                    self._trailers_only = True

                    im = MultiDict()
                    im, = await self._dispatch.recv_initial_metadata(im)
                    self.initial_metadata = im

                    tm = decode_metadata(headers)
                    tm, = await self._dispatch.recv_trailing_metadata(tm)
                    self.trailing_metadata = tm

                    self._raise_for_grpc_status(headers_map)
                else:
                    im = decode_metadata(headers)
                    im, = await self._dispatch.recv_initial_metadata(im)
                    self.initial_metadata = im

        except StreamTerminatedError:
            # Server can send RST_STREAM frame right after sending trailers-only
            # response, so we have to check received headers and probably raise
            # more descriptive error
            headers = self._stream.recv_headers_nowait()
            if headers is None:
                raise
            else:
                headers_map = dict(headers)
                self._raise_for_status(headers_map)
                if 'grpc-status' in headers_map:  # trailers-only response
                    self._raise_for_grpc_status(headers_map)
                # If there are no errors in the headers, just reraise original
                # StreamTerminatedError
                raise

    async def recv_message(self):
        """Coroutine to receive incoming message from the server.

        If server sends UNARY response, then you can call this coroutine only
        once. If server sends STREAM response, then you should call this
        coroutine several times, until it returns None. To simplify you code in
        this case, :py:class:`Stream` implements async iterations protocol, so
        you can use it like this:

        .. code-block:: python3

            async for massage in stream:
                do_smth_with(message)

        or even like this:

        .. code-block:: python3

            messages = [msg async for msg in stream]

        HTTP/2 has flow control mechanism, so client will acknowledge received
        DATA frames as a message only after user consumes this coroutine.

        :returns: message
        """
        if not self._recv_initial_metadata_done:
            await self.recv_initial_metadata()

        with self._wrapper:
            message = await recv_message(self._stream, self._codec,
                                         self._recv_type)
            if message is not NOTHING:
                message, = await self._dispatch.recv_message(message)
                return message

    async def recv_trailing_metadata(self):
        """Coroutine to wait for trailers with trailing metadata from the
        server.

        .. note:: This coroutine will be called implicitly at exit from
            this call (context manager's exit), if not called before explicitly.

        May raise :py:class:`~grpclib.exceptions.GRPCError` if server returned
        non-:py:attr:`Status.OK <grpclib.const.Status.OK>` in trailers.

        When this coroutine finishes, you can access received trailing metadata
        by using :py:attr:`trailing_metadata` attribute.
        """
        if not self._end_done:
            raise ProtocolError('Outgoing stream was not ended')

        if not self._recv_initial_metadata_done:
            raise ProtocolError('Initial metadata was not received before '
                                'waiting for trailing metadata')

        if self._recv_trailing_metadata_done:
            raise ProtocolError('Trailing metadata was already received')

        if self._trailers_only:
            self._recv_trailing_metadata_done = True
        else:
            with self._wrapper:
                headers = await self._stream.recv_headers()
                self._recv_trailing_metadata_done = True

                tm = decode_metadata(headers)
                tm, = await self._dispatch.recv_trailing_metadata(tm)
                self.trailing_metadata = tm

                self._raise_for_grpc_status(dict(headers))

    async def cancel(self):
        """Coroutine to cancel this request/stream.

        Client will send RST_STREAM frame to the server, so it will be
        explicitly informed that there is nothing to expect from the client
        regarding this request/stream.
        """
        if not self._send_request_done:
            raise ProtocolError('Request was not sent yet')

        if self._cancel_done:
            raise ProtocolError('Stream was already cancelled')

        with self._wrapper:
            await self._stream.reset()  # TODO: specify error code
            self._cancel_done = True

    async def __aenter__(self):
        if self._deadline is None:
            self._wrapper = Wrapper()
        else:
            self._wrapper = DeadlineWrapper()
            self._wrapper_ctx = self._wrapper.start(self._deadline)
            self._wrapper_ctx.__enter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if not self._send_request_done:
            return
        try:
            if (
                not exc_type
                and not self._cancel_done
                and not self._stream._transport.is_closing()
            ):
                if not self._recv_initial_metadata_done:
                    await self.recv_initial_metadata()
                if not self._recv_trailing_metadata_done:
                    await self.recv_trailing_metadata()
        finally:
            if self._stream.closable:
                self._stream.reset_nowait()
            self._release_stream()
            if self._wrapper_ctx is not None:
                self._wrapper_ctx.__exit__(exc_type, exc_val, exc_tb)


class Channel:
    """
    Represents a connection to the server, which can be used with generated
    stub classes to perform gRPC calls.

    .. code-block:: python3

        channel = Channel()
        client = cafe_grpc.CoffeeMachineStub(channel)

        ...

        request = cafe_pb2.LatteOrder(
            size=cafe_pb2.SMALL,
            temperature=70,
            sugar=3,
        )
        reply: empty_pb2.Empty = await client.MakeLatte(request)

        ...

        channel.close()
    """
    _protocol = None

    def __init__(self, host=None, port=None, *, loop=None,  path=None,
                 codec=None, ssl=None):
        """Initialize connection to the server

        :param host: server host name.

        :param port: server port number.

        :param loop: asyncio-compatible event loop

        :param path: server socket path. If specified, host and port should be
            omitted (must be None).

        :param codec: instance of a codec to encode and decode messages,
            if omitted ``ProtoCodec`` is used by default

        :param ssl: ``True`` or :py:class:`~python:ssl.SSLContext` object; if
            ``True``, default SSL context is used.
        """
        if path is not None and (host is not None or port is not None):
            raise ValueError("The 'path' parameter can not be used with the "
                             "'host' or 'port' parameters.")
        else:
            if host is None:
                host = '127.0.0.1'

            if port is None:
                port = 50051

        self._host = host
        self._port = port
        self._loop = loop or asyncio.get_event_loop()
        self._path = path

        self._codec = codec or ProtoCodec()

        self._config = H2Configuration(client_side=True,
                                       header_encoding='ascii')
        self._authority = '{}:{}'.format(self._host, self._port)

        if ssl is True:
            ssl = self._get_default_ssl_context()

        self._ssl = ssl or None
        self._scheme = 'https' if self._ssl else 'http'
        self._connect_lock = asyncio.Lock(loop=self._loop)

        self.__dispatch__ = _DispatchChannelEvents()

    def __repr__(self):
        return ('Channel({!r}, {!r}, ..., path={!r})'
                .format(self._host, self._port, self._path))

    def _protocol_factory(self):
        return H2Protocol(Handler(), self._config, loop=self._loop)

    async def _create_connection(self):
        if self._path is not None:
            _, protocol = await self._loop.create_unix_connection(
                self._protocol_factory, self._path, ssl=self._ssl)
        else:
            _, protocol = await self._loop.create_connection(
                self._protocol_factory, self._host, self._port,
                ssl=self._ssl)
        return protocol

    @property
    def _connected(self):
        return (self._protocol is not None
                and not self._protocol.handler.connection_lost)

    async def __connect__(self):
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
            self._connect_lock = asyncio.Lock(loop=self._loop)

        if not self._connected:
            async with self._connect_lock:
                if not self._connected:
                    self._protocol = await self._create_connection()
        return self._protocol

    # https://python-hyper.org/projects/h2/en/stable/negotiating-http2.html
    def _get_default_ssl_context(self):
        if not ssl:
            raise RuntimeError('SSL is not supported.')

        ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
        ctx.options |= (ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1)
        ctx.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20')
        ctx.set_alpn_protocols(['h2'])
        try:
            ctx.set_npn_protocols(['h2'])
        except NotImplementedError:
            pass

        return ctx

    def request(self, name, cardinality, request_type, reply_type,
                *, timeout=None, deadline=None, metadata=None):
        if timeout is not None and deadline is None:
            deadline = Deadline.from_timeout(timeout)
        elif timeout is not None and deadline is not None:
            deadline = min(Deadline.from_timeout(timeout), deadline)

        metadata = MultiDict(metadata or ())

        return Stream(self, name, metadata, cardinality,
                      request_type, reply_type, codec=self._codec,
                      dispatch=self.__dispatch__, deadline=deadline)

    def close(self):
        """Closes connection to the server.
        """
        if self._protocol is not None:
            self._protocol.processor.close()
            del self._protocol

    def __del__(self):
        if self._loop is not None and self._protocol is not None:
            message = 'Unclosed connection: {!r}'.format(self)
            warnings.warn(message, ResourceWarning)
            if self._loop.is_closed():
                return
            else:
                self.close()
                self._loop.call_exception_handler({'message': message})


class ServiceMethod:
    """
    Base class for all gRPC method types
    """
    def __init__(self, channel: Channel, name, request_type, reply_type):
        self.channel = channel
        self.name = name
        self.request_type = request_type
        self.reply_type = reply_type

    def __init_subclass__(cls, cardinality, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._cardinality = cardinality

    def open(self, *, timeout=None, metadata=None) -> Stream:
        """Creates and returns :py:class:`Stream` object to perform request
        to the server.

        Nothing will happen to the current underlying HTTP/2 connection during
        this method call. It just initializes :py:class:`Stream` object for you.
        Actual request will be sent only during :py:meth:`Stream.send_request`
        or :py:meth:`Stream.send_message` coroutine call.

        :param float timeout: request timeout (seconds)
        :param metadata: custom request metadata, dict or list of pairs
        :return: :py:class:`Stream` object
        """
        return self.channel.request(self.name, self._cardinality,
                                    self.request_type, self.reply_type,
                                    timeout=timeout, metadata=metadata)


class UnaryUnaryMethod(ServiceMethod, cardinality=Cardinality.UNARY_UNARY):
    """
    Represents UNARY-UNARY gRPC method type.

    .. autocomethod:: __call__
    .. autocomethod:: open
        :async-with:
    """
    async def __call__(self, message, *, timeout=None, metadata=None):
        """Coroutine to perform defined call.

        :param message: message
        :param float timeout: request timeout (seconds)
        :param metadata: custom request metadata, dict or list of pairs
        :return: message
        """
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            await stream.send_message(message, end=True)
            return await stream.recv_message()


class UnaryStreamMethod(ServiceMethod, cardinality=Cardinality.UNARY_STREAM):
    """
    Represents UNARY-STREAM gRPC method type.

    .. autocomethod:: __call__
    .. autocomethod:: open
        :async-with:
    """
    async def __call__(self, message, *, timeout=None, metadata=None):
        """Coroutine to perform defined call.

        :param message: message
        :param float timeout: request timeout (seconds)
        :param metadata: custom request metadata, dict or list of pairs
        :return: sequence of messages
        """
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            await stream.send_message(message, end=True)
            return [message async for message in stream]


class StreamUnaryMethod(ServiceMethod, cardinality=Cardinality.STREAM_UNARY):
    """
    Represents STREAM-UNARY gRPC method type.

    .. autocomethod:: __call__
    .. autocomethod:: open
        :async-with:
    """
    async def __call__(self, messages, *, timeout=None, metadata=None):
        """Coroutine to perform defined call.

        :param messages: sequence of messages
        :param float timeout: request timeout (seconds)
        :param metadata: custom request metadata, dict or list of pairs
        :return: message
        """
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            for message in messages[:-1]:
                await stream.send_message(message)
            if messages:
                await stream.send_message(messages[-1], end=True)
            else:
                await stream.end()
            return await stream.recv_message()


class StreamStreamMethod(ServiceMethod, cardinality=Cardinality.STREAM_STREAM):
    """
    Represents STREAM-STREAM gRPC method type.

    .. autocomethod:: __call__
    .. autocomethod:: open
        :async-with:
    """
    async def __call__(self, messages, *, timeout=None, metadata=None):
        """Coroutine to perform defined call.

        :param messages: sequence of messages
        :param float timeout: request timeout (seconds)
        :param metadata: custom request metadata, dict or list of pairs
        :return: sequence of messages
        """
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            for message in messages[:-1]:
                await stream.send_message(message)
            if messages:
                await stream.send_message(messages[-1], end=True)
            else:
                await stream.end()
            return [message async for message in stream]
