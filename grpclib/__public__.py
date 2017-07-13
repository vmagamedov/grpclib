import enum

from functools import partial
from collections import namedtuple


_Cardinality = namedtuple('_Cardinality', 'client_streaming, server_streaming')


@enum.unique
class Cardinality(_Cardinality, enum.Enum):
    UNARY_UNARY = _Cardinality(False, False)
    UNARY_STREAM = _Cardinality(False, True)
    STREAM_UNARY = _Cardinality(True, False)
    STREAM_STREAM = _Cardinality(True, True)


Handler = namedtuple('Handler', 'func, cardinality, request_type, reply_type')
Method = namedtuple('Method', 'name, cardinality, request_type, reply_type')


class CallDescriptor:

    def __init__(self, method):
        self.method = method
        _, _, self.method_name = method.name.split('/')

    def __get__(self, instance, owner):
        if instance is None:
            return self
        method = partial(instance.channel.request, self.method)
        instance.__dict__[self.method_name] = method
        return method
