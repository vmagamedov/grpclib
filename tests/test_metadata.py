from unittest.mock import Mock

import pytest

from grpclib.metadata import Deadline, Request, Metadata
from grpclib.metadata import encode_timeout, decode_timeout
from grpclib.metadata import encode_metadata, decode_metadata
from grpclib.metadata import encode_grpc_message, decode_grpc_message


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


def test_deadline():
    assert Deadline.from_timeout(1) < Deadline.from_timeout(2)

    with pytest.raises(TypeError) as err:
        Deadline.from_timeout(1) < 'invalid'
    err.match('comparison is not supported between instances '
              'of \'Deadline\' and \'str\'')

    assert Deadline(_timestamp=1) == Deadline(_timestamp=1)

    assert Deadline.from_timeout(1) != 'invalid'


def test_headers_with_deadline():
    deadline = Mock()
    deadline.time_remaining.return_value = 0.1

    metadata = [('dominic', 'lovech')]

    assert Request(
        method='briana', scheme='dismal', path='dost', authority='lemnos',
        content_type='gazebos',
        metadata=metadata, deadline=deadline,
    ).to_headers() == [
        (':method', 'briana'),
        (':scheme', 'dismal'),
        (':path', 'dost'),
        (':authority', 'lemnos'),
        ('grpc-timeout', '100m'),
        ('te', 'trailers'),
        ('content-type', 'gazebos'),
        ('dominic', 'lovech'),
    ]

    assert Request(
        method='briana', scheme='dismal', path='dost', authority='edges',
        content_type='gazebos',
        message_type='dobson', message_encoding='patera',
        message_accept_encoding='shakers', user_agent='dowlin',
        metadata=metadata, deadline=deadline,
    ).to_headers() == [
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
    metadata = [('chagga', 'chrome')]

    assert Request(
        method='flysch', scheme='plains', path='slaps', authority='darrin',
        content_type='pemako',
        metadata=metadata,
    ).to_headers() == [
        (':method', 'flysch'),
        (':scheme', 'plains'),
        (':path', 'slaps'),
        (':authority', 'darrin'),
        ('te', 'trailers'),
        ('content-type', 'pemako'),
        ('chagga', 'chrome'),
    ]

    assert Request(
        method='flysch', scheme='plains', path='slaps', authority='sleev',
        content_type='pemako',
        message_type='deltic', message_encoding='eutexia',
        message_accept_encoding='glyptic', user_agent='chrisom',
        metadata=metadata,
    ).to_headers() == [
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


@pytest.mark.parametrize('value, output', [
    ('а^2+б^2=ц^2', '%D0%B0^2+%D0%B1^2=%D1%86^2'),
])
def test_grpc_message_encoding(value, output):
    assert encode_grpc_message(value) == output
    encode_grpc_message(value).encode('ascii')
    assert decode_grpc_message(output) == value


def test_grpc_message_decode_safe():
    # 0xFF is invalid byte in utf-8:
    # https://www.cl.cam.ac.uk/~mgk25/ucs/examples/UTF-8-test.txt
    assert (decode_grpc_message('%FF^2+%FF^2=%FF^2')
            == '\ufffd^2+\ufffd^2=\ufffd^2')


@pytest.mark.parametrize('value, output', [
    ({'regular': 'value'}, [('regular', 'value')]),  # dict-like
    ([('regular', 'value')], [('regular', 'value')]),  # list of pairs
    ({'binary-bin': b'value'}, [('binary-bin', 'dmFsdWU')])
])
def test_encode_metadata(value, output):
    assert encode_metadata(value) == output


def test_encode_metadata_errors():
    with pytest.raises(TypeError) as e1:
        encode_metadata({'regular': b'invalid'})
    e1.match('Invalid metadata value type, str expected')

    with pytest.raises(TypeError) as e2:
        encode_metadata({'binary-bin': 'invalid'})
    e2.match('Invalid metadata value type, bytes expected')


@pytest.mark.parametrize('key', [
    'grpc-internal',
    'Upper-Case',
    'invalid~character',
    ' spaces ',
])
def test_encode_metadata_invalid_key(key):
    with pytest.raises(ValueError) as err:
        encode_metadata({key: 'anything'})
    err.match('Invalid metadata key')


def test_decode_metadata_empty():
    metadata = decode_metadata([
        (':method', 'POST'),
        ('te', 'trailers'),
        ('content-type', 'application/grpc'),
        ('user-agent', 'Test'),
        ('grpc-timeout', '100m'),
    ])
    assert metadata == Metadata()


@pytest.mark.parametrize('key, value, expected', [
    ('regular', 'value', 'value'),
    ('binary-bin', 'dmFsdWU', b'value'),
])
def test_decode_metadata_regular(key, value, expected):
    metadata = decode_metadata([
        (':method', 'POST'),
        ('te', 'trailers'),
        ('content-type', 'application/grpc'),
        ('user-agent', 'Test'),
        ('grpc-timeout', '100m'),
        (key, value),
    ])
    assert metadata == Metadata({key: expected})
    assert type(metadata[key]) is type(expected)
