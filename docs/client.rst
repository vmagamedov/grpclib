Client
======

A single :py:class:`~grpclib.client.Channel` represents a single connection to
the server. Because gRPC is based on HTTP/2, there is no need to create multiple
connections to the server, many concurrent RPC calls can be performed through
a single multiplexed connection. See :doc:`overview` for more details.

.. code-block:: python3

  channel = Channel(host, port)

A single server can implement several services, so you can reuse one channel
for all corresponding service stubs:

.. code-block:: python3

  foo_svc = FooServiceStub(channel)
  bar_svc = BarServiceStub(channel)
  baz_svc = BazServiceStub(channel)

There are two ways to call RPC methods:

- simple, suitable for unary-unary calls:

  .. code-block:: python3

    reply = await stub.Method(Request())

- advanced, suitable for streaming calls:

  .. code-block:: python3

    async with stub.BiDiMethod.open() as stream:
        while True:
            task = await task_queue.get()
            if task is None:
                break
            else:
                await stream.send_message(task)
                result = await stream.recv_message()
                await result_queue.add(task)

See reference docs for all method types and for the
:py:class:`~grpclib.client.Stream` methods and attributes.

Reference
~~~~~~~~~

.. automodule:: grpclib.client
  :members: Channel, Stream, UnaryUnaryMethod, UnaryStreamMethod,
    StreamUnaryMethod, StreamStreamMethod
