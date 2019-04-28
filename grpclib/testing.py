import asyncio

from .client import Channel
from .server import Server


class _Server(asyncio.AbstractServer):

    def close(self):
        pass

    async def wait_closed(self):
        pass


class _InMemoryTransport(asyncio.Transport):

    def __init__(self, protocol, *, loop):
        super().__init__()
        self._loop = loop
        self._protocol = protocol

    def write(self, data):
        if data:
            self._loop.call_soon(self._protocol.data_received, data)

    def is_closing(self):
        return False

    def close(self):
        pass


class ChannelFor:
    """Manages specially initialised :py:class:`~grpclib.client.Channel`
    with an in-memory transport to a :py:class:`~grpclib.server.Server`

    Example:

    .. code-block:: python3

        class Greeter(GreeterBase):
            ...

        greeter = Greeter()

        async with ChannelFor([greeter]) as channel:
            stub = GreeterStub(channel)
            response = await stub.SayHello(HelloRequest(name='Dr. Strange'))
            assert response.message == 'Hello, Dr. Strange!'
    """
    _channel = None
    _server = None
    _server_protocol = None

    def __init__(self, services):
        """
        :param services: list of services you want to test
        """
        self._services = services

    async def __aenter__(self):
        """
        :return: :py:class:`~grpclib.client.Channel`
        """
        loop = asyncio.get_event_loop()

        self._server = Server(self._services, loop=loop)
        self._server._server = _Server()
        self._server_protocol = self._server._protocol_factory()

        self._channel = Channel(loop=loop)
        self._channel._protocol = self._channel._protocol_factory()

        self._channel._protocol.connection_made(
            _InMemoryTransport(self._server_protocol, loop=loop)
        )
        self._server_protocol.connection_made(
            _InMemoryTransport(self._channel._protocol, loop=loop)
        )
        return self._channel

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._channel._protocol.connection_lost(None)
        self._channel.close()

        self._server_protocol.connection_lost(None)
        self._server.close()
        await self._server.wait_closed()
