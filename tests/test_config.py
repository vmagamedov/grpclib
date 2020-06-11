from typing import Optional, cast
from dataclasses import dataclass, field

import pytest

from grpclib.config import Configuration, _range
from grpclib.config import _DEFAULT, _with_defaults, _positive, _validate
from grpclib.config import _optional, _chain, _of_type


def test_custom_default():
    @dataclass
    class Config:
        param: Optional[int] = field(
            default=_DEFAULT,
            metadata={
                'my-default': 42,
            },
        )

    cfg = Config()
    assert cfg.param is _DEFAULT

    cfg_with_defaults = _with_defaults(cfg, 'my-default')
    assert cfg_with_defaults.param == 42


def test_missing_default():
    @dataclass
    class Config:
        param: Optional[int] = field(
            default=_DEFAULT,
        )

    cfg = Config()

    with pytest.raises(KeyError):
        _with_defaults(cfg, 'my-default')


def test_default_none():
    @dataclass
    class Config:
        param: Optional[int] = field(
            default=_DEFAULT,
            metadata={
                'my-default': None,
            },
        )

    cfg = Config()
    assert cfg.param is _DEFAULT

    cfg_with_defaults = _with_defaults(cfg, 'my-default')
    assert cfg_with_defaults.param is None


def test_validate():
    @dataclass
    class Config:
        foo: Optional[float] = field(
            default=None,
            metadata={
                'validate': _optional(_chain(_of_type(int, float), _positive)),
            },
        )

        def __post_init__(self):
            _validate(self)

    assert Config().foo is None
    assert Config(foo=0.123).foo == 0.123
    assert Config(foo=42).foo == 42

    with pytest.raises(ValueError, match='"foo" should be positive'):
        assert Config(foo=0)

    with pytest.raises(TypeError, match='"foo" should be of type'):
        assert Config(foo='a')


def test_configuration():
    # all params should be optional
    config = Configuration()
    _with_defaults(config, 'client-default')
    _with_defaults(config, 'server-default')


def test_change_default():
    # all params should be optional
    @dataclass
    class Config:
        foo: Optional[float] = field(
            default=cast(None, _DEFAULT),
            metadata={
                'validate': _optional(_chain(_of_type(int, float), _positive)),
                'test-default': 1234,
            },
        )

        def __post_init__(self):
            _validate(self)

    assert _with_defaults(Config(foo=1), 'test-default').foo == 1


def test_range():
    @dataclass
    class Config:
        foo: int = field(
            default=42,
            metadata={
                'validate': _chain(_of_type(int), _range(1, 99)),
            },
        )

        def __post_init__(self):
            _validate(self)

    Config()
    Config(foo=1)
    Config(foo=99)
    with pytest.raises(ValueError, match='should be less or equal to 99'):
        Config(foo=100)
    with pytest.raises(ValueError, match='should be higher or equal to 1'):
        Config(foo=0)
