import time

from unittest.mock import Mock

import pytest

from grpclib.metadata import encode_timeout, decode_timeout, Metadata, Deadline


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


@pytest.mark.parametrize('before, timeout, after', [
    (None, 0.1, 0.1),
    (0.2, 0.1, 0.1),
    (0.1, 0.2, 0.1),
])
def test_apply_timeout(before, timeout, after):
    deadline = Deadline(time.time() + before) if before is not None else None
    metadata = Metadata([], deadline)
    metadata = metadata.apply_timeout(timeout)
    assert metadata.deadline.time_remaining() == \
        pytest.approx(after, abs=0.01)


def test_with_headers_with_deadline():
    deadline = Mock()
    deadline.time_remaining.return_value = 0.1

    metadata = Metadata([('dominic', 'lovech')], deadline)
    assert metadata.with_headers([('bossing', 'fayres')]) == [
        ('bossing', 'fayres'),
        ('dominic', 'lovech'),
        ('grpc-timeout', '100m'),
    ]


def test_with_headers_without_deadline():
    metadata = Metadata([('chagga', 'chrome')])
    assert metadata.with_headers([('caburn', 'taffia')]) == [
        ('caburn', 'taffia'),
        ('chagga', 'chrome'),
    ]
