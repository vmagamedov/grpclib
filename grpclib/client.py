import asyncio

import async_timeout

from h2.config import H2Configuration
from h2.exceptions import StreamClosedError

from .const import Status
from .stream import CONTENT_TYPES, CONTENT_TYPE, send_message, recv_message
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

    def accept(self, stream, headers):
        raise NotImplementedError('Client connection can not accept requests')

    def cancel(self, stream):
        pass

    def close(self):
        self.connection_lost = True


class Stream(StreamIterator):
    # stream state
    _send_request_done = False
    _send_message_count = 0
    _end_done = False
    _recv_initial_metadata_done = False
    _recv_message_count = 0
    _recv_trailing_metadata_done = False
    _cancel_done = False

    initial_metadata = None
    trailing_metadata = None

    def __init__(self, channel, request, send_type, recv_type):
        self._channel = channel
        self._request = request
        self._send_type = send_type
        self._recv_type = recv_type
        self._stream = None

    def _with_deadline(self):
        if self._request.deadline is not None:
            timeout = self._request.deadline.time_remaining()
            if not timeout:
                raise asyncio.TimeoutError('Deadline exceeded')
        else:
            timeout = None
        return async_timeout.timeout(timeout)

    async def send_request(self):
        if self._send_request_done:
            raise ProtocolError('Request is already sent')

        protocol = await self._channel.__connect__()
        stream = protocol.processor.connection.create_stream()
        await stream.send_request(self._request.to_headers(),
                                  _processor=protocol.processor)
        self._stream = stream
        self._send_request_done = True

    async def send_message(self, message, *, end=False):
        if not self._send_request_done:
            await self.send_request()

        if end and self._end_done:
            raise ProtocolError('Stream was already ended')

        await send_message(self._stream, message, self._send_type, end=end)
        self._send_message_count += 1
        if end:
            self._end_done = True

    async def end(self):
        if self._end_done:
            raise ProtocolError('Stream was already ended')

        await self._stream.end()
        self._end_done = True

    async def recv_initial_metadata(self):
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

            assert headers_map['content-type'] in CONTENT_TYPES, \
                headers_map['content-type']

    async def recv_message(self):
        # TODO: check that messages were sent for non-stream-stream requests
        if not self._recv_initial_metadata_done:
            await self.recv_initial_metadata()

        async with self._with_deadline():
            message = await recv_message(self._stream, self._recv_type)
            self._recv_message_count += 1
            return message

    async def recv_trailing_metadata(self):
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


class Channel:
    _protocol = None

    def __init__(self, host='127.0.0.1', port=50051, *, loop):
        self._host = host
        self._port = port
        self._loop = loop

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
                          content_type=CONTENT_TYPE,
                          # TODO: specify versions
                          user_agent='grpc-python-grpclib',
                          metadata=metadata, deadline=deadline)

        return Stream(self, request, request_type, reply_type)

    def close(self):
        if self._protocol is not None:
            self._protocol.processor.close()


class ServiceMethod:

    def __init__(self, channel, name, request_type, reply_type):
        self.channel = channel
        self.name = name
        self.request_type = request_type
        self.reply_type = reply_type

    def open(self, *, timeout=None, metadata=None) -> Stream:
        return self.channel.request(self.name, self.request_type,
                                    self.reply_type, timeout=timeout,
                                    metadata=metadata)


class UnaryUnaryMethod(ServiceMethod):

    async def __call__(self, message, *, timeout=None, metadata=None):
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            await stream.send_message(message, end=True)
            return await stream.recv_message()


class UnaryStreamMethod(ServiceMethod):

    async def __call__(self, message, *, timeout=None, metadata=None):
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            await stream.send_message(message, end=True)
            return await _to_list(stream)


class StreamUnaryMethod(ServiceMethod):

    async def __call__(self, messages, *, timeout=None, metadata=None):
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            for message in messages[:-1]:
                await stream.send_message(message)
            if messages:
                await stream.send_message(messages[-1], end=True)
            else:
                await stream.end()
            return await stream.recv_message()


class StreamStreamMethod(ServiceMethod):

    async def __call__(self, messages, *, timeout=None, metadata=None):
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            for message in messages[:-1]:
                await stream.send_message(message)
            if messages:
                await stream.send_message(messages[-1], end=True)
            else:
                await stream.end()
            return await _to_list(stream)
