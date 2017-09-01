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

    def __init__(self, timestamp):
        self.timestamp = timestamp

    def time_remaining(self):
        return max(0, self.timestamp - time.time())


class Metadata(MultiDict):

    def __init__(self, items, deadline=None):
        super().__init__(items)
        self.deadline = deadline

    def copy(self):
        metadata = super().copy()
        metadata.deadline = self.deadline
        return metadata

    @classmethod
    def from_headers(cls, headers):
        metadata = cls([(key, value) for key, value in headers
                        if not key.startswith(':')
                        and key not in {'content-type', 'te'}])
        timeout = min(map(decode_timeout, metadata.getall('grpc-timeout', [])),
                      default=None)
        if timeout is not None:
            metadata.deadline = Deadline(time.time() + timeout)
        return metadata

    def apply_timeout(self, timeout):
        timestamp = time.time() + timeout
        if self.deadline is not None:
            if self.deadline.timestamp > timestamp:
                deadline = Deadline(timestamp)
            else:
                return self
        else:
            deadline = Deadline(timestamp)
        metadata = self.copy()
        metadata.deadline = deadline
        return metadata


class RequestHeaders(namedtuple('RequestHeaders', [
    'method', 'scheme', 'path', 'authority',
    'content_type', 'message_type', 'message_encoding',
    'message_accept_encoding', 'user_agent'
])):
    __slots__ = tuple()

    def __new__(cls, method, scheme, path, *, authority=None,
                content_type, message_type=None, message_encoding=None,
                message_accept_encoding=None, user_agent=None):
        return super().__new__(cls, method, scheme, path, authority,
                               content_type, message_type, message_encoding,
                               message_accept_encoding, user_agent)

    def to_list(self, metadata):
        result = [
            (':method', self.method),
            (':scheme', self.scheme),
            (':path', self.path),
        ]
        if self.authority is not None:
            result.append((':authority', self.authority))

        if metadata.deadline is not None:
            timeout = metadata.deadline.time_remaining()
            result.append(('grpc-timeout', encode_timeout(timeout)))

        result.append(('te', 'trailers'))
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

        result.extend((k, v) for k, v in metadata.items()
                      if k != 'grpc-timeout')
        return result
