import pytest

from grpclib.config import Configuration


@pytest.fixture(name='loop')
def loop_fixture(event_loop):
    """ Shortcut """
    return event_loop


@pytest.fixture(name='config')
def config_fixture():
    return Configuration().__for_test__()
