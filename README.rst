This library is a **temporary workaround** to add support for `async/await`
syntax (`asyncio`) into current `GRPC`_ implementation from `Google`, in order
to start implementing services using asynchronous style and then switch to
proper async `GRPC`_ implementation when it will be available, without totally
rewriting your code.

**WARNING**: by using this library you are still will be using regular threads
for accepting incoming requests and sending replies, despite the fact that all
the work will be performed in the main thread in asyncio's event-loop. This,
obviously, will limit you in ability to handle concurrent requests. You will be
able to handle so many concurrent requests as how many threads you will setup
in your ``ThreadPoolExecutor``.

Protoc plugin
~~~~~~~~~~~~~

In order to use this library you will have to generate special stub files using
provided plugin, which can be used like this:

.. code-block:: shell

    $ python -m grpc_tools.protoc -I. --python_asyncgrpc_out=. helloworld.proto

This command will generate ``helloworld_pb2_asyncgrpc.py`` file.

This plugin is available for ``protoc`` compiler as
``protoc-gen-python_asyncgrpc`` executable, which would be installed by
`setuptools` into your ``PATH`` during installation of the `asyncgrpc`_
library.

Example
~~~~~~~

Working server implementation example you can see in ``example`` directory.

Here is how RPC method implementation looks like:

.. code-block:: python

    from asyncgrpc.handler import implements

    from helloworld_pb2 import HelloReply
    from helloworld_pb2_asyncgrpc import Greeter


    @implements(Greeter.SayHello)
    async def hello(message, context, *, loop):
        await asyncio.sleep(1, loop=loop)  # simulates async operation
        return HelloReply(message='Hello, {}!'.format(message.name))

Design
~~~~~~

This library also tries to help write simple services. That's why you don't
have to inherit stub classes to implement all RPC methods. You can implement
them as simple async functions.

This library also gives ability to setup service environments using simple
dependency-injection mechanism, inspired by `pytest`_ fixtures:

.. code-block:: python

    from asyncgrpc.handler import create_handler

    loop = asyncio.get_event_loop()

    functions = [hello]
    dependencies = {'loop': loop}

    create_handler(Greeter, dependencies, functions, loop=loop)

This code is from the same example. You setup environment, specify dependencies
as ``dict``, and using them just by adding "keyword-only" arguments to you
handler when it needs something from environment.

In our example above, we configured only one dependency – ``{'loop': loop}``,
and specified this dependency in our ``hello`` function as keyword-only argument
``loop``. That's simple. Imagine how this simplicity will help you test your
handlers – you just need to call simple functions and implicitly pass all their
dependencies as arguments. No need for mocking.

Status/changelog
~~~~~~~~~~~~~~~~

- ``0.1.0`` – only server implementation available and only for unary calls

.. _GRPC: http://www.grpc.io
.. _asyncgrpc: https://github.com/vmagamedov/asyncgrpc
.. _pytest: http://pytest.org/
