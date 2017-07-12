**WARNING**: this library is a prototype, under active development, please read
changelog carefully to upgrade between versions.

This project is a pure-python `gRPC`_ implementation, based on hyper-h2 project.

Protoc plugin
~~~~~~~~~~~~~

In order to use this library you will have to generate special stub files using
plugin provided, which can be used like this:

.. code-block:: shell

    $ python -m grpc_tools.protoc -I. --python_out=. --python_grpc_out=. helloworld.proto

This command will generate ``helloworld_pb2.py`` and ``helloworld_grpc.py``
files.

Plugin, which implements ``--python_grpc_out`` option is available for
``protoc`` compiler as ``protoc-gen-python_grpc`` executable, which will be
installed by ``setuptools`` into your ``PATH`` during installation of the
``asyncgrpc`` library.

Example
~~~~~~~

.. code-block:: python

    import asyncio

    from asyncgrpc.server import Server
    from asyncgrpc.client import Channel

    import helloworld_pb2
    import helloworld_grpc

    loop = asyncio.get_event_loop()

    # Server
    class Greeter(helloworld_grpc.Greeter):

        async def SayHello(self, request, context):
            message = 'Hello, {}!'.format(request.name)
            return helloworld_pb2.HelloReply(message=message)

    server = Server([Greeter()], loop=loop)
    loop.run_until_complete(server.start('127.0.0.1', 50051))

    # Client
    channel = Channel(loop=loop)
    stub = helloworld_grpc.GreeterStub(channel)

    async def make_request():
        response = await stub.SayHello(helloworld_pb2.HelloRequest(name='World'))
        assert response.message == 'Hello, World!'

    # Test request
    loop.run_until_complete(make_request())

    # Shutdown
    server.close()
    loop.run_until_complete(server.wait_closed())
    loop.close()

Where ``helloworld.proto`` contains:

.. code-block:: protobuf

    syntax = "proto3";

    package helloworld;

    service Greeter {
      rpc SayHello (HelloRequest) returns (HelloReply) {}
    }

    message HelloRequest {
      string name = 1;
    }

    message HelloReply {
      string message = 1;
    }

Changelog
~~~~~~~~~

* ``0.2.0`` - total rewrite, now pure-python, based on hyper-h2
* ``0.1.0`` – workaround implemented, only server implementation available and
  only for unary calls

.. _gRPC: http://www.grpc.io
