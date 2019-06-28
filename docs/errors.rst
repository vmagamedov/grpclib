Errors
======

:py:class:`~grpclib.exceptions.GRPCError` is a main error you should expect
on the client-side and raise occasionally on the server-side.

Expectations
~~~~~~~~~~~~

Here is an example to illustrate how errors propagate from inside the grpclib
methods back to the caller:

.. code-block:: python3

  async with stub.SomeMethod.open() as stream:
      await stream.send_message(Request(...))
      reply = await stream.recv_message()  # gRPC error received during this call

Exceptions are propagated this way:

1. :py:class:`python:asyncio.CancelledError` is raised inside
   :py:meth:`~grpclib.client.Stream.recv_message` coroutine to interrupt it
2. :py:meth:`~grpclib.client.Stream.recv_message` coroutine handles this error
   and raise :py:class:`~grpclib.exceptions.StreamTerminatedError` instead or
   other error when it is possible to explain why coroutine was cancelled
3. when the ``open()`` context-manager exits, it may handle transitive errors
   such as :py:class:`~grpclib.exceptions.StreamTerminatedError` and raise
   proper :py:class:`~grpclib.exceptions.GRPCError` instead when possible

So here is a rule of thumb: expect :py:class:`~grpclib.exceptions.GRPCError`
outside the ``open()`` context-manager:

.. code-block:: python3

  try:
      async with stub.SomeMethod.open() as stream:
          await stream.send_message(Request(...))
          reply = await stream.recv_message()
  except GRPCError as error:
      print(error.status, error.message)

Reference
~~~~~~~~~

.. automodule:: grpclib.exceptions
  :members: GRPCError, ProtocolError, StreamTerminatedError

.. automodule:: grpclib.const
  :members: Status
