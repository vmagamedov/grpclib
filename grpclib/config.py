from typing import Optional, TypeVar, Callable, Any, Union, cast
from dataclasses import dataclass, field, fields, replace


class _DefaultType:
    def __repr__(self) -> str:
        return '<default>'


_DEFAULT = _DefaultType()

_ValidatorType = Callable[[str, Any], None]

_ConfigurationType = TypeVar('_ConfigurationType')


def _optional(validator: _ValidatorType) -> _ValidatorType:
    def proc(name: str, value: Any) -> None:
        if value is not None:
            validator(name, value)
    return proc


def _chain(*validators: _ValidatorType) -> _ValidatorType:
    def proc(name: str, value: Any) -> None:
        for validator in validators:
            validator(name, value)
    return proc


def _of_type(*types: type) -> _ValidatorType:
    def proc(name: str, value: Any) -> None:
        if not isinstance(value, types):
            types_repr = ' or '.join(str(t) for t in types)
            raise TypeError(f'"{name}" should be of type {types_repr}')
    return proc


def _positive(name: str, value: Union[float, int]) -> None:
    if value <= 0:
        raise ValueError(f'"{name}" should be positive')


def _validate(config: 'Configuration') -> None:
    for f in fields(config):
        validate_fn = f.metadata.get('validate')
        if validate_fn is not None:
            value = getattr(config, f.name)
            if value is not _DEFAULT:
                validate_fn(f.name, value)


def _with_defaults(
    cls: _ConfigurationType, metadata_key: str,
) -> _ConfigurationType:
    defaults = {}
    for f in fields(cls):
        if getattr(cls, f.name) is _DEFAULT:
            if metadata_key in f.metadata:
                default = f.metadata[metadata_key]
            else:
                default = f.metadata['default']
            defaults[f.name] = default
    return replace(cls, **defaults)


@dataclass(frozen=True)
class Configuration:
    _keepalive_time: Optional[float] = field(
        default=cast(None, _DEFAULT),
        metadata={
            'validate': _optional(_chain(_of_type(int, float), _positive)),
            'server-default': 7200.0,
            'client-default': None,
            'test-default': None,
        },
    )
    _keepalive_timeout: float = field(
        default=20.0,
        metadata={
            'validate': _chain(_of_type(int, float), _positive),
        },
    )
    _keepalive_permit_without_calls: bool = field(
        default=False,
        metadata={
            'validate': _optional(_of_type(bool)),
        },
    )
    _http2_max_pings_without_data: int = field(
        default=2,
        metadata={
            'validate': _optional(_chain(_of_type(int), _positive)),
        },
    )
    _http2_min_sent_ping_interval_without_data: float = field(
        default=300,
        metadata={
            'validate': _optional(_chain(_of_type(int, float), _positive)),
        },
    )

    def __post_init__(self) -> None:
        _validate(self)

    def __for_server__(self) -> 'Configuration':
        return _with_defaults(self, 'server-default')

    def __for_client__(self) -> 'Configuration':
        return _with_defaults(self, 'client-default')

    def __for_test__(self) -> 'Configuration':
        return _with_defaults(self, 'test-default')
