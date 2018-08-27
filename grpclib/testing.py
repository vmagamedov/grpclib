from asyncio import Transport
from contextlib import contextmanager

from .client import Channel
from .server import Server


class _InMemoryTransport(Transport):

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


@contextmanager
def channel_for(services, *, loop):
    """Specially initialised :py:class:`~grpclib.client.Channel` with in-memory
    transport to a :py:class:`~grpclib.server.Server`

    Example:

    .. code-block:: python

        class Greeter(GreeterBase):
            ...

        greeter = Greeter()

        with channel_for([greeter], loop=loop) as channel:
            stub = GreeterStub(channel)
            response = await stub.SayHello(HelloRequest(name='Dr. Strange'))
            assert response.message == 'Hello, Dr. Strange!'

    :param services: list of services you want to test
    :param loop: asyncio-compatible event loop
    :return: context-manager, which returns a channel
    """
    server = Server(services, loop=loop)
    server_protocol = server._protocol_factory()

    channel = Channel(loop=loop)
    channel._protocol = channel._protocol_factory()

    to_client_transport = _InMemoryTransport(channel._protocol, loop=loop)
    to_server_transport = _InMemoryTransport(server_protocol, loop=loop)

    channel._protocol.connection_made(to_server_transport)
    server_protocol.connection_made(to_client_transport)

    try:
        yield channel
    finally:
        server_protocol.connection_lost(None)
        channel._protocol.connection_lost(None)
