import asyncio

import pytest
import pytest_asyncio

from grpclib.config import Configuration


@pytest_asyncio.fixture(name='loop')
async def loop_fixture():
    """ Shortcut """
    return asyncio.get_running_loop()


@pytest.fixture(name='config')
def config_fixture():
    return Configuration().__for_test__()
