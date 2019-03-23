Events
======

.. automodule:: grpclib.events
  :members: listen

Common
~~~~~~

.. automodule:: grpclib.events
  :members: SendMessage, RecvMessage

Client-Side
~~~~~~~~~~~

See also :py:class:`~grpclib.events.SendMessage` and
:py:class:`~grpclib.events.RecvMessage`. You can listen for them on the
client-side.

.. automodule:: grpclib.events
  :members: SendRequest, RecvInitialMetadata, RecvTrailingMetadata

Server-Side
~~~~~~~~~~~

See also :py:class:`~grpclib.events.RecvMessage` and
:py:class:`~grpclib.events.SendMessage`. You can listen for them on the
server-side.

.. automodule:: grpclib.events
  :members: RecvRequest, SendInitialMetadata, SendTrailingMetadata
