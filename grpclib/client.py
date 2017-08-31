import asyncio

import h2.config
import async_timeout

from .stream import CONTENT_TYPES, CONTENT_TYPE, Stream as _Stream
from .protocol import H2Protocol, AbstractHandler
from .metadata import Metadata


class Handler(AbstractHandler):
    connection_lost = False

    def accept(self, stream, headers):
        raise NotImplementedError('Client connection can not accept requests')

    def cancel(self, stream):
        pass

    def close(self):
        self.connection_lost = True


class Stream(_Stream):
    _reply_headers = None
    _ended = False

    def __init__(self, channel, headers, metadata, send_type, recv_type):
        self._channel = channel
        self._headers = headers
        self._metadata = metadata
        self._send_type = send_type
        self._recv_type = recv_type

    def _with_deadline(self):
        if self._metadata.deadline is not None:
            timeout = self._metadata.deadline.time_remaining()
            if not timeout:
                raise asyncio.TimeoutError('Deadline exceeded')
        else:
            timeout = None
        return async_timeout.timeout(timeout)

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._ended:
            return

        if exc_type or exc_val or exc_tb:
            await self.reset()
        else:
            await self.end()
            async with self._with_deadline():
                trailers = dict(await self._stream.recv_headers())
                if trailers.get('grpc-status') != '0':
                    raise Exception(trailers)  # TODO: proper exception type

    async def send(self, message, end=False):
        if self._stream is None:
            protocol = await self._channel.__connect__()
            # TODO: check concurrent streams count and maybe wait
            self._stream = protocol.processor.create_stream()
            headers = self._metadata.with_headers(self._headers)
            await self._stream.send_headers(headers)

        await super().send(message, end=end)
        if end:
            assert not self._ended
            self._ended = True

    async def end(self):
        await self._stream.end()

    async def recv(self):
        async with self._with_deadline():
            if self._reply_headers is None:
                self._reply_headers = dict(await self._stream.recv_headers())
                assert self._reply_headers[':status'] == '200', \
                    self._reply_headers[':status']
                assert self._reply_headers['content-type'] in CONTENT_TYPES, \
                    self._reply_headers['content-type']

            return await super().recv()


class Channel:
    _protocol = None

    def __init__(self, host='127.0.0.1', port=50051, *, loop):
        self._host = host
        self._port = port
        self._loop = loop

        self._config = h2.config.H2Configuration(client_side=True,
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
                metadata=None):
        if metadata is None:
            metadata = Metadata([])
        else:
            if not isinstance(metadata, Metadata):
                raise TypeError('"metadata" should be of {!r} type'
                                .format(Metadata))
        if timeout is not None:
            metadata = metadata.apply_timeout(timeout)
        headers = [
            (':scheme', 'http'),
            (':authority', self._authority),
            (':method', 'POST'),
            (':path', name),
            # TODO: specify versions
            ('user-agent', 'grpc-python-grpclib (asyncio; h2)'),
            ('content-type', CONTENT_TYPE),
            ('te', 'trailers'),
        ]
        return Stream(self, headers, metadata, request_type, reply_type)

    def close(self):
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
            await stream.send(message, end=True)
            return await stream.recv()


class UnaryStreamMethod(ServiceMethod):

    async def __call__(self, message, *, timeout=None, metadata=None):
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            await stream.send(message, end=True)
            return [message async for message in stream]


class StreamUnaryMethod(ServiceMethod):

    async def __call__(self, messages, *, timeout=None, metadata=None):
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            for message in messages[:-1]:
                await stream.send(message)
            if messages:
                await stream.send(messages[-1], end=True)
            else:
                await stream.end()
            return await stream.recv()


class StreamStreamMethod(ServiceMethod):

    async def __call__(self, messages, *, timeout=None, metadata=None):
        async with self.open(timeout=timeout, metadata=metadata) as stream:
            for message in messages[:-1]:
                await stream.send(message)
            if messages:
                await stream.send(messages[-1], end=True)
            else:
                await stream.end()
            return [message async for message in stream]
