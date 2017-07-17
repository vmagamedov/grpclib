import enum

from collections import namedtuple


_Cardinality = namedtuple('_Cardinality', 'client_streaming, server_streaming')


@enum.unique
class Cardinality(_Cardinality, enum.Enum):
    UNARY_UNARY = _Cardinality(False, False)
    UNARY_STREAM = _Cardinality(False, True)
    STREAM_UNARY = _Cardinality(True, False)
    STREAM_STREAM = _Cardinality(True, True)


Handler = namedtuple('Handler', 'func, cardinality, request_type, reply_type')
