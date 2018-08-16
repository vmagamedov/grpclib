import asyncio

from contextlib import contextmanager


class Wrapper:
    """Special wrapper for coroutines to wake them up in case of some error.

    Example:

    .. code-block:: python

        w = Wrapper()

        async def blocking_call():
            with w:
                await asyncio.sleep(10)

        # and somewhere else:
        w.cancel(NoNeedToWaitError('With explanation'))

    """
    _error = None
    _task = None

    cancelled = None

    def __enter__(self):
        if self._task is not None:
            raise RuntimeError('Concurrent call detected')

        if self._error is not None:
            raise self._error

        self._task = asyncio.Task.current_task()
        assert self._task is not None, 'Called not inside a task'

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._task = None
        if self._error is not None:
            raise self._error

    def cancel(self, error):
        self._error = error
        if self._task is not None:
            self._task.cancel()
        self.cancelled = True


class DeadlineWrapper(Wrapper):
    """Deadline wrapper to specify deadline once for any number of awaiting
    method calls.

    Example:

    .. code-block:: python

        dw = DeadlineWrapper()

        with dw.start(deadline):
            await handle_request()

        # somewhere during request handling:

        async def blocking_call():
            with dw:
                await asyncio.sleep(10)

    """
    @contextmanager
    def start(self, deadline, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        timeout = deadline.time_remaining()
        if not timeout:
            raise asyncio.TimeoutError('Deadline exceeded')

        def callback():
            self.cancel(asyncio.TimeoutError('Deadline exceeded'))

        timer = loop.call_later(timeout, callback)
        try:
            yield self
        finally:
            timer.cancel()


def _service_name(service):
    methods = service.__mapping__()
    method_name = next(iter(methods), None)
    assert method_name is not None
    _, service_name, _ = method_name.split('/')
    return service_name
