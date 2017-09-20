Assuming you are in ``example`` directory.

To generate ``*_pb2.py`` and ``*_grpc.py`` files:

.. code-block:: shell

    $ python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. --python_grpc_out=. greeter/helloworld.proto

To start server:

.. code-block:: shell

    $ python3 -m greeter.server

To run client:

.. code-block:: shell

    $ python3 -m greeter.client
