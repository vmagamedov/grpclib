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
can learn gRPC wire protocol in more details here:
`gRPC format <https://github.com/grpc/grpc/blob/master/doc/PROTOCOL-HTTP2.md>`_.

gRPC has 4 method types: unary-unary, unary-stream (e.g. download),
stream-unary (e.g. upload), stream-stream. They are all the same, the only
difference is how many messages are sent in each direction: exactly one (unary)
or any number of messages (stream).

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
