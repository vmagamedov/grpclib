Client
======

A single :py:class:`~grpclib.client.Channel` represents a single connection to
the server. Because gRPC is based on HTTP/2, there is no need to create multiple
connections to the server, many concurrent RPC calls can be performed through
a single multiplexed connection. See :doc:`overview` for more details.

.. code-block:: python3

  async with Channel(host, port) as channel:
      pass

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
        await stream.send_request()  # needed to initiate a call
        while True:
            task = await task_queue.get()
            if task is None:
                await stream.end()
                break
            else:
                await stream.send_message(task)
                result = await stream.recv_message()
                await result_queue.add(task)

See reference docs for all method types and for the
:py:class:`~grpclib.client.Stream` methods and attributes.

Secure Channels
~~~~~~~~~~~~~~~

Here is how to establish a secure connection to a public gRPC server:

.. code-block:: python3

  channel = Channel(host, port, ssl=True)
                                ^^^^^^^^

In this case ``grpclib`` uses system CA certificates. But ``grpclib`` has also
a built-in support for a certifi_ package which contains actual Mozilla's
collection of CA certificates. All you need is to install it and keep it up to
date -- this is a more favorable way than relying on system CA certificates:

.. code-block:: console

  $ pip3 install certifi

Another way to tell which CA certificates to use is by using
:py:func:`python:ssl.get_default_verify_paths` function:

.. code-block:: python

  channel = Channel(host, port, ssl=ssl.get_default_verify_paths())
                                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This function also supports reading ``SSL_CERT_FILE`` and ``SSL_CERT_DIR``
environment variables to override your system defaults. It returns
``DefaultVerifyPaths`` named tuple structure which you can customize and provide
your own ``cafile`` and ``capath`` values without using environment variables or
placing certificates into a distribution-specific directory:

.. code-block:: python3

  ssl.get_default_verify_paths()._replace(cafile=YOUR_CA_FILE)

``grpclib`` also allows you to use a custom SSL configuration by providing a
:py:class:`~python:ssl.SSLContext` object. We have a simple mTLS auth example
in our code repository to illustrate how this works.

Reference
~~~~~~~~~

.. automodule:: grpclib.client
  :members: Channel, Stream, UnaryUnaryMethod, UnaryStreamMethod,
    StreamUnaryMethod, StreamStreamMethod

.. _certifi: https://github.com/certifi/python-certifi
