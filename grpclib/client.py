from h2.config import H2Configuration

from .stream import recv, send
from .protocol import H2Protocol, AbstractHandler


_CONTENT_TYPES = {'application/grpc', 'application/grpc+proto'}


class Handler(AbstractHandler):
    connection_lost = False

    def accept(self, stream, headers):
        raise NotImplementedError('Client connection can not accept requests')

    def cancel(self, stream):
        pass

    def close(self):
        self.connection_lost = True


class Stream:
    _stream = None
    _reply_headers = None
    _ended = False

    def __init__(self, channel, request_headers, request_type, reply_type):
        self._channel = channel
        self._request_headers = request_headers
        self._request_type = request_type
        self._reply_type = reply_type

    async def __aenter__(self):
        protocol = await self._channel.__connect__()

        # TODO: check concurrent streams count and maybe wait
        self._stream = protocol.processor.create_stream()

        await self._stream.send_headers(self._request_headers)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._ended:
            return

        if exc_type or exc_val or exc_tb:
            await self.reset()
        else:
            await self.end()
            trailers = dict(await self._stream.recv_headers())
            if trailers.get('grpc-status') != '0':
                raise Exception(trailers)  # TODO: proper exception type

    async def send(self, message, end=False):
        await send(self._stream, message, end_stream=end)
        if end:
            self._ended = True

    async def end(self):
        await self._stream.end()

    async def reset(self):
        await self._stream.reset()  # TODO: specify error code

    async def recv(self):
        if self._reply_headers is None:
            self._reply_headers = dict(await self._stream.recv_headers())
            assert self._reply_headers[':status'] == '200', \
                self._reply_headers[':status']
            assert self._reply_headers['content-type'] in _CONTENT_TYPES, \
                self._reply_headers['content-type']

        return await recv(self._stream, self._reply_type)

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.recv()
        if message is None:
            raise StopAsyncIteration()
        else:
            return message


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

    def _request(self, name, request_type, reply_type):
        headers = [
            (':scheme', 'http'),
            (':authority', self._authority),
            (':method', 'POST'),
            (':path', name),
            ('user-agent', 'grpc-python'),
            ('content-type', 'application/grpc+proto'),
            ('te', 'trailers'),
        ]
        return Stream(self, headers, request_type, reply_type)

    async def unary_unary(self, name, request_type, reply_type, message):
        stream = self._request(name, request_type, reply_type)
        async with stream:
            await stream.send(message, end=True)
            return await stream.recv()

    def unary_stream(self, name, request_type, reply_type):
        return self._request(name, request_type, reply_type)

    def stream_unary(self, name, request_type, reply_type):
        return self._request(name, request_type, reply_type)

    def stream_stream(self, name, request_type, reply_type):
        return self._request(name, request_type, reply_type)

    def close(self):
        self._protocol.processor.close()
