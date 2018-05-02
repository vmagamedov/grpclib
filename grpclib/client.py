import asyncio

import async_timeout

from h2.config import H2Configuration
from h2.exceptions import StreamClosedError

from .const import Status
from .stream import ProtocolBuffersCodec
from .stream import StreamIterator
from .protocol import H2Protocol, AbstractHandler
from .metadata import Metadata, Request, Deadline
from .exceptions import GRPCError, ProtocolError


async def _to_list(stream):
    result = []
    async for message in stream:
        result.append(message)
    return result


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

    .. code-block:: python

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
    _send_message_count = 0
    _end_done = False
    _recv_initial_metadata_done = False
    _recv_message_count = 0
    _recv_trailing_metadata_done = False
    _cancel_done = False

    _stream = None
    _release_stream = None

    initial_metadata = None
    trailing_metadata = None

    def __init__(self, channel, request, send_type, recv_type, *, codec=None):
        self._channel = channel
        self._request = request
        self._send_type = send_type
        self._recv_type = recv_type
        self._codec = codec or ProtocolBuffersCodec

    def _with_deadline(self):
        if self._request.deadline is not None:
            timeout = self._request.deadline.time_remaining()
            if not timeout:
                raise asyncio.TimeoutError('Deadline exceeded')
        else:
            timeout = None
        return async_timeout.timeout(timeout)

    async def send_request(self):
        """Coroutine to send request headers with metadata to the server.

        New HTTP/2 stream will be created during this coroutine call.

        .. note:: This coroutine will be called implicitly during first
            :py:meth:`send_message` coroutine call, if not called before
            explicitly.
        """
        if self._send_request_done:
            raise ProtocolError('Request is already sent')

        protocol = await self._channel.__connect__()
        stream = protocol.processor.connection.create_stream()
        release_stream = await stream.send_request(
            self._request.to_headers(), _processor=protocol.processor,
        )
        self._stream = stream
        self._release_stream = release_stream
        self._send_request_done = True

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

        if end and self._end_done:
            raise ProtocolError('Stream was already ended')

        await self._codec.send_message(self._stream, message, self._send_type, end=end)
        self._send_message_count += 1
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
        if self._end_done:
            raise ProtocolError('Stream was already ended')

        await self._stream.end()
        self._end_done = True

    async def recv_initial_metadata(self):
        """Coroutine to wait for headers with initial metadata from the server.

        .. note:: This coroutine will be called implicitly during first
            :py:meth:`recv_message` coroutine call, if not called before
            explicitly.

        May raise :py:class:`~grpclib.exceptions.GRPCError` if server returned
        non-:py:attr:`Status.OK <grpclib.const.Status.OK>` in trailers-only
        response.
        """
        if not self._send_request_done:
            raise ProtocolError('Request was not sent yet')

        if self._recv_initial_metadata_done:
            raise ProtocolError('Initial metadata was already received')

        async with self._with_deadline():
            headers = await self._stream.recv_headers()
            self._recv_initial_metadata_done = True

            self.initial_metadata = Metadata.from_headers(headers)

            headers_map = dict(headers)
            assert headers_map[':status'] == '200', headers_map[':status']

            status_code = headers_map.get('grpc-status')
            if status_code is not None:
                status = Status(int(status_code))
                if status is not Status.OK:
                    status_message = headers_map.get('grpc-message')
                    raise GRPCError(status, status_message)

            assert headers_map['content-type'] in self._codec.CONTENT_TYPES, \
                headers_map['content-type']

    async def recv_message(self):
        """Coroutine to receive incoming message from the server.

        If server sends UNARY response, then you can call this coroutine only
        once. If server sends STREAM response, then you should call this
        coroutine several times, until it returns None. To simplify you code in
        this case, :py:class:`Stream` implements async iterations protocol, so
        you can use it like this:

        .. code-block:: python

            async for massage in stream:
                do_smth_with(message)

        or even like this:

        .. code-block:: python

            messages = [msg async for msg in stream]

        HTTP/2 has flow control mechanism, so client will acknowledge received
        DATA frames as a message only after user consumes this coroutine.

        :returns: protobuf message
        """
        # TODO: check that messages were sent for non-stream-stream requests
        if not self._recv_initial_metadata_done:
            await self.recv_initial_metadata()

        async with self._with_deadline():
            message = await self._codec.recv_message(self._stream, self._recv_type)
            self._recv_message_count += 1
            return message

    async def recv_trailing_metadata(self):
        """Coroutine to wait for trailers with trailing metadata from the
        server.

        .. note:: This coroutine will be called implicitly at exit from
            this call (context manager's exit), if not called before explicitly.

        May raise :py:class:`~grpclib.exceptions.GRPCError` if server returned
        non-:py:attr:`Status.OK <grpclib.const.Status.OK>` in trailers.
        """
        if not self._recv_message_count:
            raise ProtocolError('No messages were received before waiting '
                                'for trailing metadata')

        if self._recv_trailing_metadata_done:
            raise ProtocolError('Trailing metadata was already received')

        async with self._with_deadline():
            headers = await self._stream.recv_headers()
            self._recv_trailing_metadata_done = True

            self.trailing_metadata = Metadata.from_headers(headers)

            headers_map = dict(headers)
            status_code = headers_map['grpc-status']
            status_message = headers_map.get('grpc-message')
            status = Status(int(status_code))
            if status is not Status.OK:
                raise GRPCError(status, status_message)

    async def cancel(self):
        """Coroutine to cancel this request/stream.

        Client will send RST_STREAM frame to the server, so it will be
        explicitly informed that there is nothing to expect from the client
        regarding this request/stream.
        """
        if self._cancel_done:
            raise ProtocolError('Stream was already cancelled')

        try:
            await self._stream.reset()  # TODO: specify error code
        except StreamClosedError:
            pass
        self._cancel_done = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        try:
            if (
                self._recv_trailing_metadata_done
                or self._cancel_done
                or not self._send_request_done
            ):
                return

            if exc_type or exc_val or exc_tb:
                await self.cancel()
            else:
                await self.recv_trailing_metadata()
        finally:
            if self._release_stream is not None:
                self._release_stream()


class Channel:
    """
    Represents a connection to the server, which can be used with generated
    stub classes to perform gRPC calls.

    .. code-block:: python

        channel = Channel(loop=loop)
        client = cafe_grpc.CoffeeMachineStub(channel)

        ...

        request = cafe_pb2.LatteOrder(
            size=cafe_pb2.SMALL,
            temperature=70,
            sugar=3,
        )
        reply: empty_pb2.Empty = await client.MakeLatte(request)
    """
    _protocol = None

    def __init__(self, host='127.0.0.1', port=50051, *, loop, codec=ProtocolBuffersCodec):
        self._host = host
        self._port = port
        self._loop = loop
        self._codec = codec

        self._config = H2Configuration(client_side=True,
                                       header_encoding='utf-8')
        self._authority = '{}:{}'.format(self._host, self._port)

    def _protocol_factory(self):
        return H2Protocol(Handler(), self._config, loop=self._loop)

    async def __connect__(self):
        if self._protocol is None or self._protocol.handler.connection_lost:
            _, self._protocol = await self._loop.create_connection(
                self._protocol_factory, self._host, self._port
            )
        return self._protocol

    def request(self, name, request_type, reply_type, *, timeout=None,
                deadline=None, metadata=None):
        if timeout is not None and deadline is None:
            deadline = Deadline.from_timeout(timeout)
        elif timeout is not None and deadline is not None:
            deadline = min(Deadline.from_timeout(timeout), deadline)
        else:
            deadline = None

        request = Request('POST', 'http', name, authority=self._authority,
                          content_type=self._codec.CONTENT_TYPE,
                          # TODO: specify versions
                          user_agent='grpc-python-grpclib',
                          metadata=metadata, deadline=deadline)

        return Stream(self, request, request_type, reply_type, codec=self._codec)

    def close(self):
        """Closes connection to the server.
        """
        if self._protocol is not None:
            self._protocol.processor.close()


class ServiceMethod:
    """
    Base class for all gRPC method types
    """
    def __init__(self, channel, name, request_type, reply_type):
        self.channel = channel
        self.name = name
        self.request_type = request_type
        self.reply_type = reply_type

    def open(self, *, timeout=None, metadata=None) -> Stream:
        """Creates and returns :py:class:`Stream` object to perform request
        to the server.

        Nothing will happen to the current underlying HTTP/2 connection during
        this method call. It just initializes :py:class:`Stream` object for you.
        Actual request will be sent only during :py:meth:`Stream.send_request`
        or :py:meth:`Stream.send_message` coroutine call.

        :param float timeout: request timeout (seconds)
        :param dict metadata: request metadata
        :return: :py:class:`Stream` object
        """
        return self.channel.request(self.name, self.request_type,
                                    self.reply_type, timeout=timeout,
                                    metadata=metadata)


class UnaryUnaryMethod(ServiceMethod):
    """
    Represents UNARY-UNARY gRPC method type.

    .. autocomethod:: __call__
    .. autocomethod:: open
        :async-with:
    """
    async def __call__(self, message, *, timeout=None, metadata=None):
        """Coroutine to perform defined call.

        :param message: protobuf message
        :param float timeout: request timeout (seconds)
        :param dict metadata: request metadata
        :return: protobuf message
        """
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            await stream.send_message(message, end=True)
            return await stream.recv_message()


class UnaryStreamMethod(ServiceMethod):
    """
    Represents UNARY-STREAM gRPC method type.

    .. autocomethod:: __call__
    .. autocomethod:: open
        :async-with:
    """
    async def __call__(self, message, *, timeout=None, metadata=None):
        """Coroutine to perform defined call.

        :param message: protobuf message
        :param float timeout: request timeout (seconds)
        :param dict metadata: request metadata
        :return: sequence of protobuf messages
        """
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            await stream.send_message(message, end=True)
            return await _to_list(stream)


class StreamUnaryMethod(ServiceMethod):
    """
    Represents STREAM-UNARY gRPC method type.

    .. autocomethod:: __call__
    .. autocomethod:: open
        :async-with:
    """
    async def __call__(self, messages, *, timeout=None, metadata=None):
        """Coroutine to perform defined call.

        :param messages: sequence of protobuf messages
        :param float timeout: request timeout (seconds)
        :param dict metadata: request metadata
        :return: protobuf message
        """
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            for message in messages[:-1]:
                await stream.send_message(message)
            if messages:
                await stream.send_message(messages[-1], end=True)
            else:
                await stream.end()
            return await stream.recv_message()


class StreamStreamMethod(ServiceMethod):
    """
    Represents STREAM-STREAM gRPC method type.

    .. autocomethod:: __call__
    .. autocomethod:: open
        :async-with:
    """
    async def __call__(self, messages, *, timeout=None, metadata=None):
        """Coroutine to perform defined call.

        :param messages: sequence of protobuf messages
        :param float timeout: request timeout (seconds)
        :param dict metadata: request metadata
        :return: sequence of protobuf messages
        """
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            for message in messages[:-1]:
                await stream.send_message(message)
            if messages:
                await stream.send_message(messages[-1], end=True)
            else:
                await stream.end()
            return await _to_list(stream)
