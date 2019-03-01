Server
======

Single :py:class:`~grpclib.server.Server` can serve arbitrary
number of services:

.. code-block:: python

  server = Server([services], loop=loop)

To monitor health of your services you can use standard gRPC health checking
protocol, details are here: :doc:`health`.

There is a special gRPC reflection protocol to inspect running servers and call
their methods using command-line tools, details are here: :doc:`reflection`.
It is as simple as using curl.

And it is also important to handle server's exit properly:

.. code-block:: python

  with graceful_exit([server]):
      await server.start(host, port)
      await server.wait_closed()

:py:func:`~grpclib.utils.graceful_exit` helps you handle ``SIGINT``
(during development) and ``SIGTERM`` (on production) signals.

When things become complicated you can start using
:py:class:`~python:contextlib.AsyncExitStack` and
:py:func:`~python:contextlib.asynccontextmanager` to manage lifecycle of your
application:

.. code-block:: python

  async with AsyncExitStack() as stack:
      db = await stack.enter_async_context(setup_db())
      foo_svc = await stack.enter_async_context(setup_foo_svc())

      bar_svc = BarService(db, foo_svc)
      server = Server([bar_svc], loop=loop)
      stack.enter_context(graceful_exit([server], loop=loop))
      await server.start(host, port)
      await server.wait_closed()

Reference
~~~~~~~~~

.. automodule:: grpclib.server
  :members: Server, Stream

.. automodule:: grpclib.utils
  :members: graceful_exit
