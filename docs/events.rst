Events
======

You can :py:func:`~grpclib.events.listen` for client-side events by using
:py:class:`~grpclib.client.Channel` instance as a target:

.. code-block:: python

    from grpclib.events import SendRequest

    channel = Channel(loop=loop)

    async def send_request(event: SendRequest):
        event.metadata['injected'] = 'successfully'

    listen(channel, SendRequest, send_request)

For the server-side events you can :py:func:`~grpclib.events.listen`
:py:class:`~grpclib.server.Server` instance:

.. code-block:: python

    from grpclib.events import RecvRequest

    server = Server([service], loop=loop)

    async def recv_request(event: RecvRequest):
        print(event.metadata.get('injected'))

    listen(server, RecvRequest, recv_request)

There are two types of event properties:

- **mutable**: you can change/mutate these properties and this will have
  an effect
- **read-only**: you can only read them

Listening callbacks are called in order: first added, first called. Each
callback can :py:meth:`event.interrupt` sequence of calls for a particular
event:

.. code-block:: python

    async def authn_error(stream):
        raise GRPCError(Status.UNAUTHENTICATED)

    async def recv_request(event: RecvRequest):
        if event.metadata.get('auth-token') != SECRET:
            event.method_func = authn_error
            event.interrupt()

    listen(server, RecvRequest, recv_request)

Common
~~~~~~

.. automodule:: grpclib.events
  :members: listen, SendMessage, RecvMessage

Client-Side
~~~~~~~~~~~

See also :py:class:`~grpclib.events.SendMessage` and
:py:class:`~grpclib.events.RecvMessage`. You can listen for them on the
client-side.

.. automodule:: grpclib.events
  :members: SendRequest, RecvInitialMetadata, RecvTrailingMetadata

Server-Side
~~~~~~~~~~~

See also :py:class:`~grpclib.events.RecvMessage` and
:py:class:`~grpclib.events.SendMessage`. You can listen for them on the
server-side.

.. automodule:: grpclib.events
  :members: RecvRequest, SendInitialMetadata, SendTrailingMetadata
