from typing import Type, Optional, Callable, TYPE_CHECKING, Coroutine
from collections import defaultdict

from multidict import MultiDict

from .metadata import Deadline


class _Event:
    __slots__ = ('__interrupted__',)
    __payload__ = ()
    __readonly__ = frozenset()

    def __init__(self, **kwargs):
        assert len(kwargs) == len(self.__slots__)
        super().__setattr__('__interrupted__', False)
        for key, value in kwargs.items():
            super().__setattr__(key, value)

    def __setattr__(self, key, value):
        if key in self.__readonly__:
            raise AttributeError('Read-only property: {!r}'.format(key))
        else:
            super().__setattr__(key, value)

    def interrupt(self):
        super().__setattr__('__interrupted__', True)


class _EventMeta(type):

    def __new__(mcs, name, bases, params):
        annotations = params.get('__annotations__') or {}
        payload = params.get('__payload__') or ()
        params['__slots__'] = tuple(name for name in annotations)
        params['__readonly__'] = frozenset(name for name in annotations
                                           if name not in payload)
        return super().__new__(mcs, name, bases, params)


async def _ident(*args, **_):
    return args


def _dispatches(event_type):
    def decorator(func):
        func.__dispatches__ = event_type
        return func
    return decorator


class _Dispatch:
    __dispatch_methods__ = {}

    def __init__(self):
        self._listeners = defaultdict(list)
        for name in self.__dispatch_methods__.values():
            self.__dict__[name] = _ident

    def add_listener(self, event_type: Type[_Event], callback):
        self.__dict__.pop(self.__dispatch_methods__[event_type], None)
        self._listeners[event_type].append(callback)

    async def __dispatch__(self, event: _Event):
        for callback in self._listeners[event.__class__]:
            await callback(event)
            if event.__interrupted__:
                break
        return tuple(getattr(event, name) for name in event.__payload__)


class _DispatchMeta(type):

    def __new__(mcs, name, bases, params):
        dispatch_methods = {}
        for key, value in params.items():
            dispatches = getattr(value, '__dispatches__', None)
            if dispatches is not None:
                assert (isinstance(dispatches, type)
                        and issubclass(dispatches, _Event)), dispatches
                assert dispatches not in dispatch_methods, dispatches
                dispatch_methods[dispatches] = key
        params['__dispatch_methods__'] = dispatch_methods
        return super().__new__(mcs, name, bases, params)


def listen(target, event_type, callback):
    """Register a listener function for the given target and event type

    .. code-block:: python

        async def callback(event: RequestReceived):
            print(event.data)

        listen(server, RequestReceived, callback)
    """
    target.__dispatch__.add_listener(event_type, callback)


if TYPE_CHECKING:
    from . import server  # noqa


class RecvRequest(_Event, metaclass=_EventMeta):
    """Dispatches when request was received
    """
    __payload__ = ('metadata', 'method_func')

    metadata: MultiDict
    method_func: Callable[['server.Stream'], Coroutine]
    method_name: str
    deadline: Optional[Deadline]
    content_type: str


class _DispatchServerEvents(_Dispatch, metaclass=_DispatchMeta):

    @_dispatches(RecvRequest)
    async def recv_request(self, metadata, method_func,
                           *, method_name, deadline, content_type):
        return await self.__dispatch__(RecvRequest(
            metadata=metadata,
            method_func=method_func,
            method_name=method_name,
            deadline=deadline,
            content_type=content_type,
        ))


class SendRequest(_Event, metaclass=_EventMeta):
    """Dispatches when request is about to send
    """
    __payload__ = ('metadata',)

    metadata: MultiDict
    method_name: str
    deadline: Optional[Deadline]
    content_type: str


class _DispatchChannelEvents(_Dispatch, metaclass=_DispatchMeta):

    @_dispatches(SendRequest)
    async def send_request(self, metadata, *, method_name, deadline,
                           content_type):
        return await self.__dispatch__(SendRequest(
            metadata=metadata,
            method_name=method_name,
            deadline=deadline,
            content_type=content_type,
        ))
