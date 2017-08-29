import re


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
