Changelog
=========

0.3.0rc3
~~~~~~~~

  - Added example of using ``ProcessPoolExecutor`` for CPU-intensive tasks
  - Covered examples and most user-facing apis with type annotations, many
    thanks and credit to Callum Ryan @c-ryan747 for his work on #64
  - Fixed implicit trailers-only response for streaming calls
  - Added ``end`` argument to the ``client.Stream.send_request`` method
  - **BREAKING:** Removed deprecated ``end`` argument from the
    ``server.Stream.send_message`` method
  - Fixed server to send content-type header in a trailers-only responses
  - Implemented support for the trailers-only empty response on the client-side
  - Made ``loop`` argument optional in a user-facing apis
  - Added more checks to verify that streams are used accordingly to the gRPC
    protocol spec
  - **BREAKING:** Undocumented ``Channel.request`` method was changed in a
    backward-incompatible way
  - Dropped Python 3.5 support for async generators and better typing support
  - **BREAKING:** Removed undocumented ``grpclib.metadata.Metadata`` class
  - Implemented ability to listen for "events" from grpclib, see
    :doc:`../events` for more information

0.2.5
~~~~~

  - Fixed ``protocol.Stream.send_data`` method to properly wait for a positive
    window size

0.2.4
~~~~~

  - Fixed and refactored protocol.Buffer class to properly acknowledge received
    data, which is critical for flow control mechanism. Also added logic to
    acknowledge all unread by user data before and after stream release.

0.2.3
~~~~~

  - Removed circular references and added tests to detect them
  - Generate ``*_grpc.py`` stub files even if service definitions don't exist
    in the .proto files
  - Fixed bug in the Channel.request method, deadline argument was ignored
  - Implemented ``graceful_exit`` context-manager

0.2.2
~~~~~

  - Logging StreamTerminatedError on the server-side if client resets stream
  - Improved health checks support
  - Stream methods now can be called concurrently
  - Fixed flow-control window change detection for the case when the other party
    relies on connection-level window with unlimited stream-level windows
  - Fixed PING frame support on the server-side

0.2.1
~~~~~

  - Added ``Channel.__del__`` method to close unclosed connections and warn
    about them
  - Changed user-agent header to reflect ``grpclib`` and Python versions
  - Added workaround for ``h2``, when ``h2`` raises ``StreamIDTooLowError``
    instead of ``StreamClosedError``
  - Fixed race condition in the ``Channel``, which leads to creation of more
    than one connection
  - Fixed Python 3.5.1 compatibility

0.2.0
~~~~~

  - Fixed flow control functionality
  - Generate ``*_grpc.py`` stub files only if service definitions exists in the
    .proto files
  - Fixed possibility of the infinite loop when we reach max outbound streams
    limit and wait for a closed stream during
    :py:meth:`grpclib.protocol.Stream.send_request` method call
  - Added support for secure channels through SSL/TLS; pull request courtesy
    Michael P. Nitowski @mnito
  - Implemented Health service with additional functionality to help write
    health checks
  - Implemented ``ChannelFor`` helper for writing functional tests
  - Added support for UNIX sockets; pull request courtesy Andy Kipp @kippandrew
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
    Elsdörfer @miracle2k
  - Improved error responses and errors handling
  - Deprecated ``end`` keyword-only argument in the
    :py:meth:`grpclib.server.Stream.send_message` method on the server-side

0.1.0
~~~~~

  - Improved example to show all RPC method types; pull request courtesy @claws
  - [rc2] Fixed issues with sending large messages
  - [rc1] Initial release
