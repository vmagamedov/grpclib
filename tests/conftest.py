import asyncio

import pytest

from grpclib.config import Configuration


@pytest.fixture(name='loop')
async def loop_fixture():
    """ Shortcut """
    return asyncio.get_running_loop()


@pytest.fixture(name='config')
def config_fixture():
    return Configuration().__for_test__()
