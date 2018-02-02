import re
import time

from collections import namedtuple

from multidict import MultiDict


_UNITS = {
    'H': 60 * 60,
    'M': 60,
    'S': 1,
    'm': 10 ** -3,
    'u': 10 ** -6,
    'n': 10 ** -9,
}

_TIMEOUT_RE = re.compile('^(\d+)([{}])$'.format(''.join(_UNITS)))


def decode_timeout(value):
    match = _TIMEOUT_RE.match(value)
    if match is None:
        raise ValueError('Invalid timeout: {}'.format(value))
    timeout, unit = match.groups()
    return int(timeout) * _UNITS[unit]


def encode_timeout(timeout):
    if timeout > 10:
        return '{}S'.format(int(timeout))
    elif timeout > 0.01:
        return '{}m'.format(int(timeout * 10 ** 3))
    elif timeout > 0.00001:
        return '{}u'.format(int(timeout * 10 ** 6))
    else:
        return '{}n'.format(int(timeout * 10 ** 9))


class Deadline:

    def __init__(self, *, _timestamp):
        self._timestamp = _timestamp

    def __lt__(self, other):
        if not isinstance(other, Deadline):
            raise TypeError('comparison is not supported between '
                            'instances of \'{}\' and \'{}\''
                            .format(type(self).__name__, type(other).__name__))
        return self._timestamp < other._timestamp

    def __eq__(self, other):
        if not isinstance(other, Deadline):
            return False
        return self._timestamp == other._timestamp

    @classmethod
    def from_metadata(cls, metadata):
        timeout = min(map(decode_timeout,
                          metadata.getall('grpc-timeout', [])),
                      default=None)
        if timeout is not None:
            return cls.from_timeout(timeout)
        else:
            return None

    @classmethod
    def from_timeout(cls, timeout):
        return cls(_timestamp=time.monotonic() + timeout)

    def time_remaining(self):
        return max(0, self._timestamp - time.monotonic())


class Metadata(MultiDict):
    _headers = {'content-type', 'te'}

    @classmethod
    def from_headers(cls, headers):
        return cls([(key, value) for key, value in headers
                    if not key.startswith(':') and key not in cls._headers])


class Request(namedtuple('Request', [
    'method', 'scheme', 'path', 'authority',
    'content_type', 'message_type', 'message_encoding',
    'message_accept_encoding', 'user_agent',
    'metadata', 'deadline',
])):
    __slots__ = tuple()

    def __new__(cls, method, scheme, path, *, authority,
                content_type=None, message_type=None, message_encoding=None,
                message_accept_encoding=None, user_agent=None,
                metadata=None, deadline=None):
        return super().__new__(cls, method, scheme, path, authority,
                               content_type, message_type, message_encoding,
                               message_accept_encoding, user_agent,
                               metadata, deadline)

    def to_headers(self):
        result = [
            (':method', self.method),
            (':scheme', self.scheme),
            (':path', self.path),
            (':authority', self.authority),
        ]

        if self.deadline is not None:
            timeout = self.deadline.time_remaining()
            result.append(('grpc-timeout', encode_timeout(timeout)))

        result.append(('te', 'trailers'))

        if self.content_type is not None:
            result.append(('content-type', self.content_type))

        if self.message_type is not None:
            result.append(('grpc-message-type', self.message_type))

        if self.message_encoding is not None:
            result.append(('grpc-encoding', self.message_encoding))

        if self.message_accept_encoding is not None:
            result.append(('grpc-accept-encoding',
                           self.message_accept_encoding))

        if self.user_agent is not None:
            result.append(('user-agent', self.user_agent))

        if self.metadata is not None:
            result.extend((k, v) for k, v in self.metadata.items()
                          if k != 'grpc-timeout')
        return result
