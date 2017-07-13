from grpclib.protocol import _slice


def test_slice():
    data, tail = _slice([b'a', b'b', b'c', b'd', b'e', b'f'], 5)
    assert data == [b'a', b'b', b'c', b'd', b'e']
    assert tail == [b'f']

    data, tail = _slice([b'a', b'b', b'cdef'], 5)
    assert data == [b'a', b'b', b'cde']
    assert tail == [b'f']

    data, tail = _slice([b'abc', b'def', b'gh'], 5)
    assert data == [b'abc', b'de']
    assert tail == [b'f', b'gh']

    data, tail = _slice([b'abcde', b'fgh'], 5)
    assert data == [b'abcde']
    assert tail == [b'fgh']

    data, tail = _slice([b'abcdefgh', b'ij'], 5)
    assert data == [b'abcde']
    assert tail == [b'fgh', b'ij']

    data, tail = _slice([b'abcdefgh', b'ij'], 100)
    assert data == [b'abcdefgh', b'ij']
    assert tail == []
