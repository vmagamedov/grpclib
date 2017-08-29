import pytest

from grpclib.client import _apply_timeout


@pytest.mark.parametrize('timeout, final_timeout', [
    (0.05, '50m'),
    (0.15, '100m'),
    (0.25, '100m'),
])
def test_apply_timeout(timeout, final_timeout):
    metadata = [
        ('rollo', 'bobbers'),
        ('grpc-timeout', '100m'),
        ('kyar', 'penmen'),
        ('grpc-timeout', '200m'),
        ('upbear', 'bailer'),
    ]
    assert list(_apply_timeout(metadata, timeout)) == [
        ('rollo', 'bobbers'),
        ('kyar', 'penmen'),
        ('upbear', 'bailer'),
        ('grpc-timeout', final_timeout),
    ]
