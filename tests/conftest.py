import socket

import pytest


@pytest.fixture()
def loop(event_loop):
    """ Shortcut """
    return event_loop


@pytest.fixture(name='addr')
def addr_fixture():
    host = '127.0.0.1'
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        _, port = s.getsockname()
    return host, port
