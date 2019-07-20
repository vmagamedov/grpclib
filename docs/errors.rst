Errors
======

:py:class:`~grpclib.exceptions.GRPCError` is a main error you should expect
on the client-side and raise occasionally on the server-side.

Client-Side
~~~~~~~~~~~

Here is an example to illustrate how errors propagate from inside the grpclib
methods back to the caller:

.. code-block:: python3

  async with stub.SomeMethod.open() as stream:
      await stream.send_message(Request(...))
      reply = await stream.recv_message()  # gRPC error received during this call

Exceptions are propagated this way:

1. :py:class:`~python:asyncio.CancelledError` is raised inside
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

Server-Side
~~~~~~~~~~~

Here is an example to illustrate how request cancellation is performed:

.. code-block:: python3

  class Greeter(GreeterBase):
      async def SayHello(self, stream):
          try:
              ...
              await asyncio.sleep(1)  # cancel happens here
              ...
          finally:
              pass  # cleanup

1. Task running ``SayHello`` coroutine gets cancelled and
   :py:class:`~python:asyncio.CancelledError` is raised inside it
2. You can use try..finally clause and/or context managers to properly cleanup
   used resources
3. When ``SayHello`` coroutine finishes, grpclib server internally re-raises
   :py:class:`~python:asyncio.CancelledError` as
   :py:class:`~python:asyncio.TimeoutError` or
   :py:class:`~grpclib.exceptions.StreamTerminatedError` to explain why request
   was cancelled
4. If cancellation isn't performed clearly, e.g. ``SayHello`` raises another
   exception instead of :py:class:`~python:asyncio.CancelledError`, this error
   is logged.

Reference
~~~~~~~~~

.. automodule:: grpclib.exceptions
  :members: GRPCError, ProtocolError, StreamTerminatedError

.. automodule:: grpclib.const
  :members: Status
