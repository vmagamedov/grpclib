import asyncio

import pytest

from grpclib.metadata import Deadline
from grpclib.utils import Wrapper, DeadlineWrapper


class CustomError(Exception):
    pass


class UserAPI:

    def __init__(self, wrapper):
        self.wrapper = wrapper

    async def foo(self, *, time=.0001):
        with self.wrapper:
            await asyncio.sleep(time)


@pytest.mark.asyncio
async def test_wrapper(loop):
    api = UserAPI(Wrapper())
    await api.foo()

    loop.call_soon(lambda: api.wrapper.cancel(CustomError('Some explanation')))

    with pytest.raises(CustomError) as err:
        await api.foo()
    err.match('Some explanation')

    with pytest.raises(CustomError):
        await api.foo()


@pytest.mark.asyncio
async def test_wrapper_concurrent(loop):
    api = UserAPI(Wrapper())

    t1 = loop.create_task(api.foo(time=1))
    t2 = loop.create_task(api.foo(time=1))

    loop.call_soon(lambda: api.wrapper.cancel(CustomError('Some explanation')))

    await asyncio.wait([t1, t2], timeout=0.01)

    assert t1.done()
    assert t2.done()
    e1 = t1.exception()
    e2 = t2.exception()
    assert e1 and e2 and e1 is e2
    assert isinstance(e1, CustomError)
    assert e1.args == ('Some explanation',)


@pytest.mark.asyncio
async def test_deadline_wrapper(loop):
    deadline = Deadline.from_timeout(0.01)
    deadline_wrapper = DeadlineWrapper()
    api = UserAPI(deadline_wrapper)

    with deadline_wrapper.start(deadline, loop=loop):
        await api.foo(time=0.0001)

        with pytest.raises(asyncio.TimeoutError) as err:
            await api.foo(time=0.1)
        assert err.match('Deadline exceeded')

        with pytest.raises(asyncio.TimeoutError) as err:
            await api.foo(time=0.0001)
        assert err.match('Deadline exceeded')
