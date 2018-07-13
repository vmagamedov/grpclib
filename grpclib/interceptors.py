import functools


class BaseInterceptor:
    async def on_request(self, stream, call_handler):
        await call_handler(stream)

    async def before_send(self, stream, message):
        return message

    async def after_send(self, stream, message):
        pass


def wrap_method(method, interceptors):
    interceptors = interceptors or []

    handler = method
    for interceptor in interceptors[::-1]:
        handler = functools.partial(
            interceptor.on_request, call_handler=handler
        )

    return handler
