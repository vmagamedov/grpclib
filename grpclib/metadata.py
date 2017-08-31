import re
import time

from itertools import chain

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

    def with_headers(self, headers):
        result = [(key, value) for key, value in chain(headers, self.items())
                  if key != 'grpc-timeout']
        if self.deadline is not None:
            timeout = self.deadline.time_remaining()
            result.append(('grpc-timeout', encode_timeout(timeout)))
        return result
