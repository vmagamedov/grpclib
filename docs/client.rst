Client
======

Single :py:class:`~grpclib.client.Channel` represents single connection to the
server. Because gRPC is based on HTTP/2, there is no need to create multiple
connections to the server, many concurrent RPC calls can be performed through
a single multiplexed connection. See :doc:`overview` for more details.

.. code-block:: python3

  a_channel = Channel(a_host, a_port)

``Channel`` can also be shared between all service stubs, if those services are
implemented by the server, to which this channel is connected to.

.. code-block:: python3

  foo_svc = FooServiceStub(a_channel)
  bar_svc = BarServiceStub(a_channel)
  baz_svc = BazServiceStub(a_channel)

gRPC protocol supports four method types:

============================================= ==============================================
:py:class:`~grpclib.client.UnaryUnaryMethod`  :py:class:`~grpclib.client.UnaryStreamMethod`
--------------------------------------------- ----------------------------------------------
:py:class:`~grpclib.client.StreamUnaryMethod` :py:class:`~grpclib.client.StreamStreamMethod`
============================================= ==============================================

There are two ways to call these method types:

- simple:

  .. code-block:: python3

    reply = await stub.Method(Request())

- advanced:

  .. code-block:: python3

    async with stub.Method.open() as stream:
        await stream.send_message(Request())
        reply = stream.recv_message()

Simple way is so simple that it isn't using async generators to deal with
streaming requests and responses - streaming methods accepts and returns
simple synchronous sequences. To overcome this issue you may use
``async with method.open() as stream:`` context-manager and you will be able
to control every detail of a RPC call:

.. code-block:: python3

  async with stub.SomeBiDiMethod.open(metadata=request_metadata) as stream:
      await stream.send_request()
      await stream.recv_initial_metadata()
      print(stream.initial_metadata)
      while True:
          task = await task_queue.get()
          if task is None:
              break
          else:
              await stream.send_message(task)
              result = await stream.recv_message()
              await result_queue.add(task)
      await stream.end()
      await stream.recv_trailing_metadata()
      print(stream.trailing_metadata)

See reference docs for all method types and for the
:py:class:`~grpclib.client.Stream` methods and attributes.

Reference
~~~~~~~~~

.. automodule:: grpclib.client
  :members: Channel, Stream, UnaryUnaryMethod, UnaryStreamMethod,
    StreamUnaryMethod, StreamStreamMethod
