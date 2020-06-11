Configuration
=============

:py:class:`~grpclib.client.Channel` and :py:class:`~grpclib.server.Server`
classes accepts configuration via :py:class:`~grpclib.config.Configuration`
object to modify default behaviour.

Example:

.. code-block:: python3

  from grpclib.config import Configuration

  config = Configuration(
      http2_connection_window_size=2**20,  # 1 MiB
  )
  channel = Channel('localhost', 50051, config=config)

Reference
~~~~~~~~~

.. automodule:: grpclib.config
  :members: Configuration
