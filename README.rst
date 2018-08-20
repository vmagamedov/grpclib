This project is a pure-Python `gRPC`_ implementation, based on `hyper-h2`_
project, **requires Python >= 3.5**.

Licensed under **BSD-3-Clause** license. See LICENSE.txt

**Motivation:** ``grpclib`` is intended to implement gRPC protocol in Python
once for all concurrency models. However, currently ``grpclib`` supports only
``asyncio`` library and only with ``async/await`` syntax.

**Note:** Python 2.7 support is not planned, but you can use official `grpcio`_
library for projects with such requirements.

Installation
~~~~~~~~~~~~

.. code-block:: shell

    $ pip3 install grpclib protobuf

For the code generation you will also need a ``protoc`` compiler, which can be
installed with ``protobuf`` system package:

.. code-block:: shell

    $ brew install protobuf  # example for macOS users
    $ protoc --version
    libprotoc ...


**Or** you can use ``protoc`` compiler from the ``grpcio-tools`` Python package:

.. code-block:: shell

    $ pip3 install grpcio-tools
    $ python3 -m grpc_tools.protoc --version
    libprotoc ...

**Note:** ``grpcio`` and ``grpcio-tools`` packages are **not required in
runtime**, ``grpcio-tools`` package will be used only during code generation.

Protoc plugin
~~~~~~~~~~~~~

In order to use this library you will have to generate special stub files using
plugin provided, which can be used like this:

.. code-block:: shell

    $ python3 -m grpc_tools.protoc -I. --python_out=. --python_grpc_out=. helloworld/helloworld.proto

This command will generate ``helloworld_pb2.py`` and ``helloworld_grpc.py``
files.

Plugin, which implements ``--python_grpc_out`` option is available for
``protoc`` compiler as ``protoc-gen-python_grpc`` executable, which will be
installed by ``setuptools`` into your ``PATH`` during installation of the
``grpclib`` library.

Example
~~~~~~~

See ``example`` directory for a full example of the ``helloworld`` service.
``example/README.rst`` contains instructions about how to generate
``helloworld_pb2.py`` and ``helloworld_grpc.py`` files and how to run example.

Example basically looks like this (for Python>=3.7):

.. code-block:: python

    import asyncio

    from grpclib.server import Server
    from grpclib.client import Channel

    from .helloworld_pb2 import HelloRequest, HelloReply
    from .helloworld_grpc import GreeterBase, GreeterStub


    class Greeter(GreeterBase):

        async def SayHello(self, stream):
            request = await stream.recv_message()
            message = f'Hello, {request.name}!'
            await stream.send_message(HelloReply(message=message))


    async def test():
        loop = asyncio.get_event_loop()

        # start server
        server = Server([Greeter()], loop=loop)
        await server.start('127.0.0.1', 50051)

        # perform request
        channel = Channel('127.0.0.1', 50051, loop=loop)
        stub = GreeterStub(channel)
        response = await stub.SayHello(HelloRequest(name='World'))
        print(response.message)

        # shutdown server
        server.close()
        await server.wait_closed()


    if __name__ == '__main__':
        asyncio.run(test())

Where ``helloworld.proto`` contains:

.. code-block:: protobuf

    syntax = "proto3";

    package helloworld;

    message HelloRequest {
      string name = 1;
    }

    message HelloReply {
      string message = 1;
    }

    service Greeter {
      rpc SayHello (HelloRequest) returns (HelloReply) {}
    }

Contributing
~~~~~~~~~~~~

Use Tox_ in order to test and lint your changes.

.. _gRPC: http://www.grpc.io
.. _hyper-h2: https://github.com/python-hyper/hyper-h2
.. _grpcio: https://pypi.org/project/grpcio/
.. _Tox: https://tox.readthedocs.io/
