Reflection
==========

Server reflection is an optional extension, which describes services,
implemented on the server.

In examples we will use ``grpc_cli`` command-line tool and ``helloworld``
example. We will use
:py:meth:`grpclib.reflection.service.ServerReflection.extend` method to add
server reflection.

Then we will be able to...

List services on the server:

.. code-block:: shell

    $ grpc_cli ls localhost:50051
    helloworld.Greeter

List methods of the service:

.. code-block:: shell

    $ grpc_cli ls localhost:50051 helloworld.Greeter -l
    filename: helloworld/helloworld.proto
    package: helloworld;
    service Greeter {
      rpc UnaryUnaryGreeting(helloworld.HelloRequest) returns (helloworld.HelloReply) {}
      rpc UnaryStreamGreeting(helloworld.HelloRequest) returns (stream helloworld.HelloReply) {}
      rpc StreamUnaryGreeting(stream helloworld.HelloRequest) returns (helloworld.HelloReply) {}
      rpc StreamStreamGreeting(stream helloworld.HelloRequest) returns (stream helloworld.HelloReply) {}
    }

Describe messages:

.. code-block:: shell

    $ grpc_cli type localhost:50051 helloworld.HelloRequest
    message HelloRequest {
      string name = 1;
    }

Call simple methods:

.. code-block:: shell

    $ grpc_cli call localhost:50051 helloworld.Greeter.UnaryUnaryGreeting "name: 'Dr. Strange'"
    connecting to localhost:50051
    message: "Hello, Dr. Strange!"

    Rpc succeeded with OK status

And all of these done without downloading .proto files and compiling them into
other source files in order to create stubs.

Reference
~~~~~~~~~

.. automodule:: grpclib.reflection.service
    :members: ServerReflection
