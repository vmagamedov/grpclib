Assuming you are in the ``example`` directory.

To start the server:

.. code-block:: shell

    $ python3 -m helloworld.server

To run the client:

.. code-block:: shell

    $ python3 -m helloworld.client

To re-generate ``helloworld_pb2.py`` and ``helloworld_grpc.py`` files (already generated):

.. code-block:: shell

    $ python3 -m grpc_tools.protoc -I. --python_out=. --python_grpc_out=. helloworld/helloworld.proto
