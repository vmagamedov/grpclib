Server
======

A single :py:class:`~grpclib.server.Server` can serve arbitrary
number of services:

.. code-block:: python3

  server = Server([foo_svc, bar_svc, baz_svc])

To monitor health of your services you can use standard gRPC health checking
protocol, details are here: :doc:`health`.

There is a special gRPC reflection protocol to inspect running servers and call
their methods using command-line tools, details are here: :doc:`reflection`.
It is as simple as using curl.

It is also important to handle server's exit properly:

.. code-block:: python3

  with graceful_exit([server]):
      await server.start(host, port)
      print(f'Serving on {host}:{port}')
      await server.wait_closed()

:py:func:`~grpclib.utils.graceful_exit` helps you handle ``SIGINT`` and
``SIGTERM`` signals.

When things become complicated you can start using
:py:class:`~python:contextlib.AsyncExitStack` and
:py:func:`~python:contextlib.asynccontextmanager` to manage lifecycle of your
application and used resources:

.. code-block:: python3

  async with AsyncExitStack() as stack:
      db = await stack.enter_async_context(setup_db())
      foo_svc = FooService(db)

      server = Server([foo_svc])
      stack.enter_context(graceful_exit([server]))
      await server.start(host, port)
      print(f'Serving on {host}:{port}')
      await server.wait_closed()

Reference
~~~~~~~~~

.. automodule:: grpclib.server
  :members: Server, Stream

.. automodule:: grpclib.utils
  :members: graceful_exit
