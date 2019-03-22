from unittest.mock import Mock, patch

import pytest

from grpclib.events import _Event, _EventMeta, _ident, listen
from grpclib.events import _Dispatch, _DispatchMeta, _dispatches


def _event_eq(self, other):
    if not isinstance(other, type(self)):
        return False
    for name in self.__slots__:
        if getattr(self, name) != getattr(other, name):
            return False
    return True


def patch_event():
    return patch.object(_Event, '__eq__', _event_eq)


def mock_callback(func):
    return Mock(side_effect=func)


def test_empty_event():
    class MyEvent(_Event, metaclass=_EventMeta):
        pass

    assert MyEvent.__slots__ == ()
    assert MyEvent.__readonly__ == frozenset()
    assert MyEvent.__payload__ == ()

    event = MyEvent()
    with pytest.raises(AttributeError, match='has no attribute'):
        event.foo = 5


def test_frozen_event():
    class MyEvent(_Event, metaclass=_EventMeta):
        a: int
        b: str

    assert set(MyEvent.__slots__) == {'a', 'b'}
    assert MyEvent.__readonly__ == frozenset(('a', 'b'))
    assert MyEvent.__payload__ == ()

    event = MyEvent(a=1, b='2')
    assert event.a == 1
    assert event.b == '2'
    with pytest.raises(AttributeError, match='^Read-only'):
        event.a = 5


def test_mixed_event():
    class MyEvent(_Event, metaclass=_EventMeta):
        __payload__ = ('a', 'b')
        a: int
        b: str
        c: int
        d: str

    assert set(MyEvent.__slots__) == {'a', 'b', 'c', 'd'}
    assert MyEvent.__readonly__ == frozenset(('c', 'd'))
    assert MyEvent.__payload__ == ('a', 'b')

    event = MyEvent(a=1, b='2', c=3, d='4')
    assert event.a == 1
    assert event.b == '2'
    assert event.c == 3
    assert event.d == '4'
    event.a = 5
    event.b = '6'
    assert event.a == 5
    assert event.b == '6'
    with pytest.raises(AttributeError, match='^Read-only'):
        event.c = 7
    with pytest.raises(AttributeError, match='^Read-only'):
        event.d = '8'


@pytest.mark.asyncio
async def test_dispatch():
    class MyEvent(_Event, metaclass=_EventMeta):
        __payload__ = ('a', 'b')
        a: int
        b: str
        c: int
        d: str

    class MyDispatch(_Dispatch, metaclass=_DispatchMeta):
        @_dispatches(MyEvent)
        async def my_event(self, a, b, *, c, d):
            return await self.__dispatch__(MyEvent(a=a, b=b, c=c, d=d))

    class Target:
        __dispatch__ = MyDispatch()

    assert Target.__dispatch__.my_event is _ident
    assert await Target.__dispatch__.my_event(1, 3, c=6, d=9) == (1, 3)

    @mock_callback
    async def callback(event: MyEvent):
        assert event.a == 2
        assert event.b == 4
        assert event.c == 8
        assert event.d == 16

    listen(Target, MyEvent, callback)

    assert Target.__dispatch__.my_event is not _ident
    assert await Target.__dispatch__.my_event(2, 4, c=8, d=16) == (2, 4)
    with patch_event():
        callback.assert_called_once_with(MyEvent(a=2, b=4, c=8, d=16))


@pytest.mark.asyncio
async def test_interrupt():
    class MyEvent(_Event, metaclass=_EventMeta):
        payload: int

    class MyDispatch(_Dispatch, metaclass=_DispatchMeta):
        @_dispatches(MyEvent)
        async def my_event(self, *, payload):
            return await self.__dispatch__(MyEvent(payload=payload))

    class Target:
        __dispatch__ = MyDispatch()

    @mock_callback
    async def cb1(_: MyEvent):
        pass

    @mock_callback
    async def cb2(event: MyEvent):
        event.interrupt()

    @mock_callback
    async def cb3(_: MyEvent):
        pass

    listen(Target, MyEvent, cb1)
    listen(Target, MyEvent, cb2)
    listen(Target, MyEvent, cb3)

    assert await Target.__dispatch__.my_event(payload=42) == ()

    cb1.assert_called_once()
    cb2.assert_called_once()
    assert not cb3.called
