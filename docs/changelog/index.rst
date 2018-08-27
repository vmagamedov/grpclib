Changelog
=========

Unreleased
~~~~~~~~~~

  - Implemented Health service with additional functionality to help write
    health checks
  - Implemented ``channel_for`` helper for writing functional tests
  - Added support for UNIX sockets; pull request courtesy Andy Kipp
  - Implemented server reflection protocol
  - **BREAKING:** Fixed metadata encoding. Previously grpclib were using
    utf-8 to encode metadata, and now grpclib encodes metadata according to the
    gRPC wire protocol specification: ascii for regular values and base64 for
    binary values
  - **BREAKING:** Fixed "grpc-message" header encoding: unicode string -> utf-8
    -> percent-encoding (RFC 3986, ascii subset). Previously solely utf-8 were
    used, which now will fail to decode, if you send non-ascii characters
  - Implemented sending custom metadata from the server-side

0.1.1
~~~~~

  - Dropped protobuf requirement, now it's optional
  - New feature to specify custom message serialization/deserialization codec
  - Fixed critical issue on the client-side with hanging coroutines in case of
    connection lost or stream reset
  - Replaced ``async-timeout`` dependency with custom utilities, refactored
    deadlines implementation
  - Improved connection lost handling; pull request courtesy Michael
    Elsdörfer
  - Improved error responses and errors handling
  - Deprecated ``end`` keyword-only argument in the
    :py:meth:`grpclib.server.Stream.send_message` method on the server-side

0.1.0
~~~~~

  - Improved example to show all RPC method types; pull request courtesy @claws
  - [rc2] Fixed issues with sending large messages
  - [rc1] Initial release
