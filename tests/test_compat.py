import importlib


def test_const_imports():
    const = importlib.import_module('grpclib.const')
    assert getattr(const, 'Cardinality')
    assert getattr(const, 'Handler')


def test_client_imports():
    client = importlib.import_module('grpclib.client')
    assert getattr(client, 'Channel')
    assert getattr(client, 'UnaryUnaryMethod')
    assert getattr(client, 'UnaryStreamMethod')
    assert getattr(client, 'StreamUnaryMethod')
    assert getattr(client, 'StreamStreamMethod')
