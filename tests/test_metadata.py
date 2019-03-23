import pytest

from multidict import MultiDict

from grpclib.metadata import Deadline
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
    assert metadata == MultiDict()


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
    assert metadata == MultiDict({key: expected})
    assert type(metadata[key]) is type(expected)
