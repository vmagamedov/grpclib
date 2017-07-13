from h2.config import H2Configuration

from .common import recv_gen, send
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

    async def _ensure_connected(self):
        if self._protocol is None or self._protocol.handler.connection_lost:
            _, self._protocol = await self._loop.create_connection(
                self._protocol_factory, self._host, self._port
            )
        return self._protocol

    async def request(self, method, request):
        protocol = await self._ensure_connected()

        # TODO: check concurrent streams count and maybe wait
        stream = protocol.processor.create_stream()

        await stream.send_headers([
            (':scheme', 'http'),
            (':authority', self._authority),
            (':method', 'POST'),
            (':path', method.name),
            ('user-agent', 'grpc-python'),
            ('content-type', 'application/grpc+proto'),
            ('te', 'trailers'),
        ])

        if method.cardinality.value.client_streaming:
            async for msg in request:
                assert isinstance(msg, method.request_type), type(msg)
                await send(stream, msg)
            await stream.end()
        else:
            assert isinstance(request, method.request_type), type(request)
            await send(stream, request, end_stream=True)

        headers = dict(await stream.recv_headers())
        assert headers[':status'] == '200', headers[':status']
        assert headers['content-type'] in _CONTENT_TYPES, \
            headers['content-type']

        if method.cardinality.server_streaming:
            return self._stream_result(stream, method)
        else:
            return await self._unary_result(stream, method)

    async def _stream_result(self, stream, method):
        async for reply in recv_gen(stream, method.reply_type):
            yield reply
        trailers = dict(await stream.recv_headers())
        if trailers.get('grpc-status') != '0':
            raise Exception(trailers)  # TODO: proper exception type

    async def _unary_result(self, stream, method):
        reply = [r async for r in recv_gen(stream, method.reply_type)]
        trailers = dict(await stream.recv_headers())
        if trailers.get('grpc-status') != '0':
            raise Exception(trailers)  # TODO: proper exception type
        assert len(reply) == 1, len(reply)
        return reply[0]

    def close(self):
        self._protocol.processor.close()
