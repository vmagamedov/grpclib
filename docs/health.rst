Health Checking
===============

GRPC provides `Health Checking Protocol`_ to implement health checks. You can
see it's latest definition here: `grpc/health/v1/health.proto`_.

As you can see from the service definition,
:py:class:`~grpclib.health.service.Health` service should implement one or two
methods: simple unary-unary ``Check`` method for synchronous checks and more
sophisticated unary-stream ``Watch`` method to asynchronously wait for status
changes. `grpclib` implements both of them.

`grpclib` also provides additional functionality to help write health checks, so
users don't have to write a lot of code on their own. It is possible to
implement health check in two ways (you can use both ways simultaneously):

  - use :py:class:`~grpclib.health.check.ServiceCheck` class by providing
    a callable object which can be called asynchronously to determine
    check's status
  - use :py:class:`~grpclib.health.check.ServiceStatus` class and change
    it's status by using :py:class:`~grpclib.health.check.ServiceStatus.set`
    method

:py:class:`~grpclib.health.check.ServiceCheck` is a simplest and most generic
way to implement periodic checks.

:py:class:`~grpclib.health.check.ServiceStatus` is for a more advanced usage,
when you are able to detect and change check's status proactively (e.g. by
detecting lost connection). And this way is more efficient and robust.

User Guide
~~~~~~~~~~

.. note:: To test server's health we will use `grpc_health_probe`_ command.

Overall Server Health
---------------------

The most simplest health checks:

.. code-block:: python

  from grpclib.health.service import Health

  health = Health()

  server = Server(handlers + [health], loop=loop)

Testing:

.. code-block:: shell

  $ grpc_health_probe -addr=localhost:50051
  healthy: SERVING

Overall server status is always ``SERVING``.

If you want to add real checks:

.. code-block:: python

  from grpclib.health.service import Health, OVERALL

  health = Health({OVERALL: [db_check, cache_check]})

Overall server status is ``SERVING`` if all checks are passing.

Detailed Services Health
------------------------

If you want to provide different checks for different services:

.. code-block:: python

  foo = FooService()
  bar = BarService()

  health = Health({
      foo: [a_check, b_check],
      bar: [b_check, c_check],
  })

Testing:

.. code-block:: shell

  $ grpc_health_probe -addr=localhost:50051 -service acme.FooService
  healthy: SERVING
  $ grpc_health_probe -addr=localhost:50051 -service acme.BarService
  healthy: NOT_SERVING
  $ grpc_health_probe -addr=localhost:50051
  healthy: NOT_SERVING

- ``acme.FooService`` is healthy if ``a_check`` and ``b_check`` are passing
- ``acme.BarService`` is healthy if ``b_check`` and ``c_check`` are passing
- Overall health status depends on all checks

You can also override checks list for overall server's health status:

.. code-block:: python

  foo = FooService()
  bar = BarService()

  health = Health({
      foo: [a_check, b_check],
      bar: [b_check, c_check],
      OVERALL: [a_check, c_check],
  })

Reference
~~~~~~~~~

.. automodule:: grpclib.health.service
    :members: Health, OVERALL

.. automodule:: grpclib.health.check
    :members: ServiceCheck, ServiceStatus

.. _Health Checking Protocol: https://github.com/grpc/grpc/blob/master/doc/health-checking.md
.. _grpc/health/v1/health.proto: https://github.com/grpc/grpc-proto/blob/master/grpc/health/v1/health.proto
.. _grpc_health_probe: https://github.com/grpc-ecosystem/grpc-health-probe
