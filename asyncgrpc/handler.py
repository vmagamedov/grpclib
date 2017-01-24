import inspect
import functools

from collections import namedtuple
from concurrent.futures import Future

import grpc


Method = namedtuple('Method', 'name, input, output')


def reduce_arity(values, func):
    if inspect.ismethod(func):
        sign = inspect.signature(func.__func__)
    else:
        sign = inspect.signature(func)
    kw_only = {p.name: values[p.name] for p in sign.parameters.values()
               if p.kind is inspect.Parameter.KEYWORD_ONLY}
    return functools.partial(func, **kw_only)


async def _async_wrapper(fn, fut, args, kwargs):
    try:
        result = await fn(*(args or ()), **(kwargs or {}))
    except Exception as e:
        fut.set_exception(e)
    else:
        fut.set_result(result)


def make_sync(func, *, loop):
    def wrapper(*args, **kwargs):
        fut = Future()
        loop.call_soon_threadsafe(
            loop.create_task,
            _async_wrapper(func, fut, args, kwargs),
        )
        return fut.result()
    return wrapper


def implements(method):
    def decorator(func):
        func.__implements__ = method
        return func
    return decorator


def create_handler(service, dependencies, functions, *, loop):
    implemented = set()
    for func in functions:
        try:
            implemented.add(func.__implements__)
        except AttributeError:
            raise TypeError('Object {!r} does not looking like '
                            'service method implementation'
                            .format(func))
    implemented = {func.__implements__ for func in functions}
    missing = service.__methods__.difference(implemented)
    if missing:
        raise TypeError('Service methods not implemented: {}'
                        .format(', '.join(repr(m.name) for m in missing)))
    unknown = implemented.difference(service.__methods__)
    if unknown:
        raise TypeError('Unknown service methods: {!r}'
                        .format(', '.join(repr(m.name) for m in unknown)))

    rpc_handlers = {
        func.__implements__.name: grpc.unary_unary_rpc_method_handler(
            make_sync(reduce_arity(dependencies, func), loop=loop),
            request_deserializer=(
                func.__implements__.input.FromString
            ),
            response_serializer=(
                func.__implements__.output.SerializeToString
            ),
        )
        for func in functions
        }

    return grpc.method_handlers_generic_handler(
        service.__service__,
        rpc_handlers,
    )
