import pytest


@pytest.fixture()
def loop(event_loop):
    """ Shortcut """
    return event_loop
