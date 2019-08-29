Errors
======

:py:class:`~grpclib.exceptions.GRPCError` is a main error you should expect
on the client-side and raise occasionally on the server-side.

Error Details
~~~~~~~~~~~~~

There is a possibility to send and receive rich error details, which may
provide much more context than status and message alone. These details are
encoded using ``google.rpc.Status`` message and sent with trailing metadata.
This message becomes available after optional package install:

.. code-block:: console

  $ pip3 install googleapis-common-protos

There are some already defined error details in the
``google.rpc.error_details_pb2`` module, but you're not limited to them, you can
send any message you want.

Here is how to send these details from the server-side:

.. code-block:: python3

  from google.rpc.error_details_pb2 import BadRequest

  async def Method(self, stream):
      ...
      raise GRPCError(
          Status.INVALID_ARGUMENT,
          'Request validation failed',
          [
              BadRequest(
                  field_violations=[
                      BadRequest.FieldViolation(
                          field='title',
                          description='This field is required',
                      ),
                  ],
              ),
          ],
      )

Here is how to dig into every detail on the client-side:

.. code-block:: python3

  from google.rpc.error_details_pb2 import BadRequest

  try:
      reply = await stub.Method(Request(...))
  except GRPCError as err:
      if err.details:
          for detail in err.details:
              if isinstance(detail, BadRequest):
                  for violation in detail.field_violations:
                      print(f'{violation.field}: {violation.description}')

.. note:: In order to automatically decode these messages (details), you have
  to import them, otherwise you will see such stubs in the list of error
  details:

  .. code-block:: text

    Unknown('google.rpc.QuotaFailure')

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
