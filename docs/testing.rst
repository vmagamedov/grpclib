Testing
=======

You can use generated stubs to test your services. But it is not needed to
setup connectivity over network interfaces. `grpclib` provides ability to use
real client-side code, real server-side code, and real h2/gRPC protocol to test
your service, with all the data sent in-memory.

Reference
~~~~~~~~~

.. automodule:: grpclib.testing
    :members: channel_for
