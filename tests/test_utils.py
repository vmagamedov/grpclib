import sys
import time
import signal
import asyncio
import subprocess
from unittest.mock import Mock

import pytest

from grpclib.utils import Wrapper, DeadlineWrapper, _cached
from grpclib.metadata import Deadline


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
async def test_deadline_wrapper():
    deadline = Deadline.from_timeout(0.01)
    deadline_wrapper = DeadlineWrapper()
    api = UserAPI(deadline_wrapper)

    with deadline_wrapper.start(deadline):
        await api.foo(time=0.0001)

        with pytest.raises(asyncio.TimeoutError) as err:
            await api.foo(time=0.1)
        assert err.match('Deadline exceeded')

        with pytest.raises(asyncio.TimeoutError) as err:
            await api.foo(time=0.0001)
        assert err.match('Deadline exceeded')


NORMAL_SERVER = """
import asyncio

from grpclib.utils import graceful_exit
from grpclib.server import Server

async def main():
    server = Server([])
    with graceful_exit([server]):
        await server.start('127.0.0.1')
        print("Started!")
        await server.wait_closed()

if __name__ == '__main__':
    asyncio.run(main())
"""


@pytest.mark.parametrize('sig_num', [signal.SIGINT, signal.SIGTERM])
def test_graceful_exit_normal_server(sig_num):
    cmd = [sys.executable, '-u', '-c', NORMAL_SERVER]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
        try:
            assert proc.stdout.readline() == b'Started!\n'
            time.sleep(0.001)
            proc.send_signal(sig_num)
            assert proc.wait(1) == 0
        finally:
            if proc.returncode is None:
                proc.kill()


SLUGGISH_SERVER = """
import asyncio

from grpclib.utils import graceful_exit
from grpclib.server import Server

async def main():
    server = Server([])
    with graceful_exit([server]):
        await server.start('127.0.0.1')
        print("Started!")
        await server.wait_closed()
        await asyncio.sleep(10)

if __name__ == '__main__':
    asyncio.run(main())
"""


@pytest.mark.parametrize('sig1, sig2', [
    (signal.SIGINT, signal.SIGINT),
    (signal.SIGTERM, signal.SIGTERM),
    (signal.SIGINT, signal.SIGTERM),
    (signal.SIGTERM, signal.SIGINT),
])
def test_graceful_exit_sluggish_server(sig1, sig2):
    cmd = [sys.executable, '-u', '-c', SLUGGISH_SERVER]
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
        try:
            assert proc.stdout.readline() == b'Started!\n'
            time.sleep(0.001)
            proc.send_signal(sig1)
            with pytest.raises(subprocess.TimeoutExpired):
                proc.wait(0.01)
            proc.send_signal(sig2)
            assert proc.wait(1) == 128 + sig2
        finally:
            if proc.returncode is None:
                proc.kill()


def test_cached():
    def func():
        return 42

    func_mock = Mock(side_effect=func)
    func_decorated = _cached(func_mock)
    assert func_mock.call_count == 0
    assert func_decorated() == 42
    assert func_decorated() == 42
    assert func_decorated() == 42
    assert func_mock.call_count == 1
