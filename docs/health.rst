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

Reference
~~~~~~~~~

.. automodule:: grpclib.health.service
    :members: Health

.. automodule:: grpclib.health.check
    :members: ServiceCheck, ServiceStatus

.. _Health Checking Protocol: https://github.com/grpc/grpc/blob/master/doc/health-checking.md
.. _grpc/health/v1/health.proto: https://github.com/grpc/grpc-proto/blob/master/grpc/health/v1/health.proto
