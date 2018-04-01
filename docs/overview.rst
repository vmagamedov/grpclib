Overview
========

gRPC protocol is exclusively based on HTTP/2 (aka h2) protocol. Main concepts:

- each request in h2 connection is a bidirectional stream of frames_;
- streams give ability to do multiplexing_ - make requests in parallel using
  single TCP connection;
- h2 has special `flow control`_ mechanism, which can help avoid network
  congestion and fix problems with slow clients, slow servers and slow network;
- flow control only affects ``DATA`` frames, any other frame can be sent
  without limitations;
- streams can be cancelled individually, all other streams in h2 connection
  will continue work and there is no need to drop connection and reconnect;
- h2 is a binary protocol and allows headers compression using HPACK_ format,
  so it is a very strict and efficient protocol.

h2 protocol is highly configurable, for example:

- `flow control`_ mechanism can use dynamically configurable
  initial window size, to better match different use cases and conditions;
- you can set maximum frame size to control how much data you will
  receive in each frame;
- you can limit number of concurrent streams for h2 connection.

gRPC protocol adds to h2 protocol messages encoding format and a notion
about metadata. gRPC metadata == additional h2 headers. So gRPC has the same
level of extensibility as HTTP has.

Messages are sent using one or several ``DATA`` frames, depending on maximum
frame size setting and message size. Messages are encoded using simple format:
prefix + data. Prefix contains length of the data and compression flag. You
can learn gRPC wire protocol in more details here: `gRPC format`_.

gRPC has 4 method types: unary-unary, unary-stream (e.g. download),
stream-unary (e.g. upload), stream-stream. They are all the same, the only
difference is how many messages are sent in each direction: exactly one (unary)
or any number of messages (stream).

Cancellation
~~~~~~~~~~~~

As it was said above, h2 allows you to cancel any stream without affecting other
streams, which are living in the same connection. And h2 protocol has special
frame to do this: RST_STREAM_. Both client and server can cancel streams.
This feature automatically gives you ability to proactively cancel gRPC method
calls in the same way. In ``grpclib`` you can cancel method calls immediately,
for example:

- client sends request to the server
- server spawns task to handle this request
- client wants to cancel this request and sends ``RST_STREAM`` frame
- server receives ``RST_STREAM`` frame and cancels task immediately

Most other protocols doesn't have this feature, so they have to terminate
whole TCP connection and perform reconnect for the next call. It is also not
obvious how to immediately detect terminated connections on the other side,
and this means that server most likely will continue result computations, when
this result is not needed anymore.

Deadlines
~~~~~~~~~

Deadlines are basically timeouts, which are propagated from service to service,
to meet initial timeout constrains. This is a simple and powerful idea.

Example:

- service X receives request with ``grpc-timeout: 100m`` in metadata
  (100m means 100 milliseconds)

  - service X immediately converts timeout into deadline:

    .. code-block:: python

      deadline = time.monotonic() + grpc_timeout

  - service X spent 20ms doing some work

  - now service X wants to make outgoing request to service Y, so it computes
    how much time remains to perform this request:

    .. code-block:: python

      new_timeout = max(deadline - time.monotonic(), 0)  # == 80ms

  - service X performs request to service Y with metadata ``grpc-timeout: 80m``

    - service Y uses the same logic to convert timeout -> deadline -> timeout.

With this feature it is possible to cancel whole call chain simultaneously,
even in case of network failures (broken connections).

grpclib
~~~~~~~

``grpclib`` tries to give you full control over these bidirectional h2 streams.

.. note:: *[auto]* mark below means that it is not necessary to explicitly call
  these methods in your code, they will be called automatically behind the
  scenes. They are exists to have more control.

.. raw:: html
   :file: _static/diagram.html

.. _frames: http://httpwg.org/specs/rfc7540.html#FrameTypes
.. _multiplexing: http://httpwg.org/specs/rfc7540.html#StreamsLayer
.. _flow control: http://httpwg.org/specs/rfc7540.html#FlowControl
.. _HPACK: http://httpwg.org/specs/rfc7541.html
.. _gRPC format: https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-HTTP2.md
.. _RST_STREAM: http://httpwg.org/specs/rfc7540.html#RST_STREAM
