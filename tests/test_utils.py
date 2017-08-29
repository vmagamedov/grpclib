import pytest

from grpclib.utils import encode_timeout, decode_timeout


@pytest.mark.parametrize('value, expected', [
    (100, '100S'),
    (15, '15S'),
    (7, '7000m'),
    (0.02, '20m'),
    (0.001, '1000u'),
    (0.00002, '20u'),
    (0.000001, '1000n'),
    (0.00000002, '20n'),
])
def test_encode_timeout(value, expected):
    assert encode_timeout(value) == expected


@pytest.mark.parametrize('value, expected', [
    ('5H', 5 * 3600),
    ('4M', 4 * 60),
    ('3S', 3),
    ('200m', pytest.approx(0.2)),
    ('100u', pytest.approx(0.0001)),
    ('50n', pytest.approx(0.00000005)),
])
def test_decode_timeout(value, expected):
    assert decode_timeout(value) == expected
