Encoding
========

GRPC supports sending messages using any encoding format, and grpclib supports
this feature as well.

By default, gRPC interprets ``application/grpc`` content type as
``application/grpc+proto`` content type. So by default gRPC uses Protocol
Buffers as encoding format.

But why content type has such name with a ``proto`` subtype? This is because
messages in gRPC are sent as length-delimited stream of binary blobs. This
format can't be changed, so content type should always be in the
form of ``application/grpc+{subtype}``, where ``{subtype}`` can be anything you
want, e.g. ``proto``, ``fbs``, ``json``, ``thrift``, ``bson``, ``msgpack``.

Codec
~~~~~

In order to use custom serialization format, you should implement
:py:class:`~grpclib.encoding.base.CodecBase` abstract base class:

.. code-block:: python3

    from grpclib.encoding.base import CodecBase

    class JSONCodec(CodecBase):
        __content_subtype__ = 'json'

        def encode(self, message, message_type):
            return json.dumps(message, ensure_ascii=False).encode('utf-8')

        def decode(self, data: bytes, message_type):
            return json.loads(data.decode('utf-8'))


If your format doesn't have interface definition language (like protocol
buffers language) and code-generation tools (like ``protoc`` compiler), you will
have to manage your server-side and client-side code yourself. JSON format
doesn't have such tools, so let's try define our server-side and client side
code.

Naming Conventions
~~~~~~~~~~~~~~~~~~

Even if you don't use Protocol Buffers for messages encoding, this language also
defines coding style for services definition. These rules are related to
service names and method names, which are used by gRPC to build ``:path`` pseudo
header::

    :path = /dotted.package.CamelCaseServiceName/CamelCaseMethodName

`Protocol Buffers Style Guide`_ says:

    You should use CamelCase (with an initial capital) for both the service name
    and any RPC method names.

Server example
~~~~~~~~~~~~~~

.. code-block:: python3

    from grpclib.const import Cardinality, Handler
    from grpclib.server import Server

    class PingServiceHandler:

        async def Ping(self, stream):
            request = await stream.recv_message()
            ...
            await stream.send_message({'value': 'pong'})

        def __mapping__(self):
            return {
                '/ping.PingService/Ping': Handler(
                    self.UnaryUnary,
                    Cardinality.UNARY_UNARY,
                    None,
                    None,
                ),
            }

    loop = asyncio.get_event_loop()
    server = Server([PingServiceHandler()], loop=loop, codec=JSONCodec())

Client example
~~~~~~~~~~~~~~

.. code-block:: python3

    from grpclib.client import Channel, UnaryUnaryMethod

    class PingServiceStub:

        def __init__(self, channel):
            self.Ping = UnaryUnaryMethod(
                channel,
                '/ping.PingService/Ping',
                None,
                None,
            )

    loop = asyncio.get_event_loop()
    channel = Channel(loop=loop, codec=JSONCodec())
    ping_stub = PingServiceStub(channel)
    ...
    await ping_stub.Ping({'value': 'ping'})

.. _Protocol Buffers Style Guide: https://developers.google.com/protocol-buffers/docs/style
