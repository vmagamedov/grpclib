Metadata
========

Structure of the gRPC call looks like this:

.. code-block:: text

    > :path /package/Method/
    > ...
    > ... request metadata

    > data (request)

    < :status 200
    < ...
    < ... initial metadata

    < data (reply)

    < grpc-status 0
    < ...
    < ... trailing metadata

The same as regular HTTP request but with trailers. So client can send request
metadata and server can return initial and trailing metadata.

Metadata sent as regular HTTP headers. It may contain printable ascii text
with spaces:

.. code-block:: text

    auth-token: 0d16ad85-6ce4-4773-a1be-9f62b2e886a3

Or it may contain binary data:

.. code-block:: text

    auth-token-bin: DRathWzkR3Ohvp9isuiGow

Binary metadata keys should contain ``-bin`` suffix and values should be encoded
using base64 encoding without padding.

Keys with ``grpc-`` prefix are reserved for gRPC protocol. You can read more
additional details here: `gRPC Wire Format`_.

``grpclib`` encodes and decodes binary metadata automatically. In Python you
will receive text metadata as ``str`` type:

.. code-block:: python

    {"auth-token": "0d16ad85-6ce4-4773-a1be-9f62b2e886a3"}

Binary metadata you will receive as ``bytes`` type:

.. code-block:: python

    {"auth-token-bin": b"\r\x16\xad\x85l\xe4Gs\xa1\xbe\x9fb\xb2\xe8\x86\xa3"}

Client-Side
~~~~~~~~~~~

Sending metadata:

.. code-block:: python

    reply = await stub.Method(Request(), metadata={'auth-token': auth_token})

Sending and receiving metadata:

.. code-block:: python

    async with stub.Method.open(metadata={'auth-token': auth_token}) as stream:
        await stream.recv_initial_metadata()
        print(stream.initial_metadata)

        await stream.send_message(Request())
        reply = await stream.recv_message()

        await stream.recv_trailing_metadata()
        print(stream.trailing_metadata)

See reference docs for more details: :doc:`client`.

Server-Side
~~~~~~~~~~~

Receiving and sending metadata:

.. code-block:: python

    class Service(ServiceBase):

        async def Method(self, stream):
            print(stream.metadata)  # request metadata

            await stream.send_initial_metadata(metadata={
                'begin-time': current_time(),
            })

            request = await stream.recv_message()
            ...
            await stream.send_message(Reply())

            await stream.send_trailing_metadata(metadata={
                'end-time': current_time(),
            })

See reference docs for more details: :doc:`server`.

Reference
~~~~~~~~~

.. automodule:: grpclib.metadata
  :members: Deadline

.. _gRPC Wire Format: https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-HTTP2.md
