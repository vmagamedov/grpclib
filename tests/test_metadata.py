import time

from unittest.mock import Mock

import pytest

from grpclib.metadata import encode_timeout, decode_timeout
from grpclib.metadata import Metadata, Deadline, RequestHeaders


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


def test_headers_with_deadline():
    deadline = Mock()
    deadline.time_remaining.return_value = 0.1

    metadata = Metadata([('dominic', 'lovech')], deadline)

    assert RequestHeaders(
        'briana', 'dismal', 'dost', content_type='gazebos',
    ).to_list(metadata) == [
        (':method', 'briana'),
        (':scheme', 'dismal'),
        (':path', 'dost'),
        ('grpc-timeout', '100m'),
        ('te', 'trailers'),
        ('content-type', 'gazebos'),
        ('dominic', 'lovech'),
    ]

    assert RequestHeaders(
        'briana', 'dismal', 'dost', authority='edges', content_type='gazebos',
        message_type='dobson', message_encoding='patera',
        message_accept_encoding='shakers', user_agent='dowlin',
    ).to_list(metadata) == [
        (':method', 'briana'),
        (':scheme', 'dismal'),
        (':path', 'dost'),
        (':authority', 'edges'),
        ('grpc-timeout', '100m'),
        ('te', 'trailers'),
        ('content-type', 'gazebos'),
        ('grpc-message-type', 'dobson'),
        ('grpc-encoding', 'patera'),
        ('grpc-accept-encoding', 'shakers'),
        ('user-agent', 'dowlin'),
        ('dominic', 'lovech'),
    ]


def test_headers_without_deadline():
    metadata = Metadata([('chagga', 'chrome')])

    assert RequestHeaders(
        'flysch', 'plains', 'slaps', content_type='pemako',
    ).to_list(metadata) == [
        (':method', 'flysch'),
        (':scheme', 'plains'),
        (':path', 'slaps'),
        ('te', 'trailers'),
        ('content-type', 'pemako'),
        ('chagga', 'chrome'),
    ]

    assert RequestHeaders(
        'flysch', 'plains', 'slaps', authority='sleev', content_type='pemako',
        message_type='deltic', message_encoding='eutexia',
        message_accept_encoding='glyptic', user_agent='chrisom',
    ).to_list(metadata) == [
        (':method', 'flysch'),
        (':scheme', 'plains'),
        (':path', 'slaps'),
        (':authority', 'sleev'),
        ('te', 'trailers'),
        ('content-type', 'pemako'),
        ('grpc-message-type', 'deltic'),
        ('grpc-encoding', 'eutexia'),
        ('grpc-accept-encoding', 'glyptic'),
        ('user-agent', 'chrisom'),
        ('chagga', 'chrome'),
    ]
