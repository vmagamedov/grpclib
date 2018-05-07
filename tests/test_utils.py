import asyncio

import pytest

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
async def test_deadline_wrapper(loop):
    deadline_wrapper = DeadlineWrapper()
    api = UserAPI(deadline_wrapper)

    with deadline_wrapper.start(0.001, loop=loop):
        await api.foo(time=0.0001)

        with pytest.raises(asyncio.TimeoutError) as err:
            await api.foo(time=0.1)
        assert err.match('Deadline exceeded')

        with pytest.raises(asyncio.TimeoutError) as err:
            await api.foo(time=0.0001)
        assert err.match('Deadline exceeded')
