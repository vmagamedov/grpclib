Changelog
=========

0.1.1
~~~~~

  - Fixed critical issue on the client-side with hanging coroutines in case of
    connection lost or stream reset
  - Replaced ``async-timeout`` dependency with custom utilities, refactored
    deadlines implementation
  - Improved connection lost handling; pull request courtesy Michael
    Elsdörfer
  - Improved error responses and errors handling
  - deprecated ``end`` keyword-only argument in the
    :py:meth:`grpclib.server.Stream.send_message` method on the server-side

0.1.0
~~~~~

  - Improved example to show all RPC method types; pull request courtesy @claws
  - [rc2] Fixed issues with sending large messages
  - [rc1] Initial release
