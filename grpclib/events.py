from typing import Type, Optional, Callable, TYPE_CHECKING, Coroutine, Any
from itertools import chain
from collections import defaultdict

from multidict import MultiDict

from .metadata import Deadline


class _Event:
    __slots__ = ('__interrupted__',)
    __payload__ = ()
    __readonly__ = frozenset()

    def __init__(self, **kwargs):
        assert len(kwargs) == len(self.__slots__), self.__slots__
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
        dispatch_methods = dict(chain.from_iterable(
            getattr(base, '__dispatch_methods__', {}).items()
            for base in bases
        ))
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
    """Registers a listener function for the given target and event type

    .. code-block:: python3

        async def callback(event: SomeEvent):
            print(event.data)

        listen(target, SomeEvent, callback)
    """
    target.__dispatch__.add_listener(event_type, callback)


class SendMessage(_Event, metaclass=_EventMeta):
    """Dispatches before sending message to the other party

    :param mutable message: message to send
    """
    __payload__ = ('message',)

    message: Any


class RecvMessage(_Event, metaclass=_EventMeta):
    """Dispatches after message was received from the other party

    :param mutable message: received message
    """
    __payload__ = ('message',)

    message: Any


class _DispatchCommonEvents(_Dispatch, metaclass=_DispatchMeta):

    @_dispatches(SendMessage)
    async def send_message(self, message):
        return await self.__dispatch__(SendMessage(
            message=message,
        ))

    @_dispatches(RecvMessage)
    async def recv_message(self, message):
        return await self.__dispatch__(RecvMessage(
            message=message,
        ))


if TYPE_CHECKING:
    from . import server  # noqa


class RecvRequest(_Event, metaclass=_EventMeta):
    """Dispatches after request was received from the client

    :param mutable metadata: invocation metadata
    :param mutable method_func: coroutine function to process this request,
        accepts :py:class:`~grpclib.server.Stream`
    :param read-only method_name: RPC's method name
    :param read-only deadline: request's :py:class:`~grpclib.metadata.Deadline`
    :param read-only content_type: request's content type
    """
    __payload__ = ('metadata', 'method_func')

    metadata: MultiDict
    method_func: Callable[['server.Stream'], Coroutine]
    method_name: str
    deadline: Optional[Deadline]
    content_type: str


class SendInitialMetadata(_Event, metaclass=_EventMeta):
    """Dispatches before sending headers with initial metadata to the client

    :param mutable metadata: initial metadata
    """
    __payload__ = ('metadata',)

    metadata: MultiDict


class SendTrailingMetadata(_Event, metaclass=_EventMeta):
    """Dispatches before sending trailers with trailing metadata to the client

    :param mutable metadata: trailing metadata
    """
    __payload__ = ('metadata',)

    metadata: MultiDict


class _DispatchServerEvents(_DispatchCommonEvents):

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

    @_dispatches(SendInitialMetadata)
    async def send_initial_metadata(self, metadata):
        return await self.__dispatch__(SendInitialMetadata(
            metadata=metadata,
        ))

    @_dispatches(SendTrailingMetadata)
    async def send_trailing_metadata(self, metadata):
        return await self.__dispatch__(SendTrailingMetadata(
            metadata=metadata,
        ))


class SendRequest(_Event, metaclass=_EventMeta):
    """Dispatches before sending request to the server

    :param mutable metadata: invocation metadata
    :param read-only method_name: RPC's method name
    :param read-only deadline: request's :py:class:`~grpclib.metadata.Deadline`
    :param read-only content_type: request's content type
    """
    __payload__ = ('metadata',)

    metadata: MultiDict
    method_name: str
    deadline: Optional[Deadline]
    content_type: str


class RecvInitialMetadata(_Event, metaclass=_EventMeta):
    """Dispatches after headers with initial metadata were received
    from the server

    :param mutable metadata: initial metadata
    """
    __payload__ = ('metadata',)

    metadata: MultiDict


class RecvTrailingMetadata(_Event, metaclass=_EventMeta):
    """Dispatches after trailers with trailing metadata were received
    from the server

    :param mutable metadata: trailing metadata
    """
    __payload__ = ('metadata',)

    metadata: MultiDict


class _DispatchChannelEvents(_DispatchCommonEvents):

    @_dispatches(SendRequest)
    async def send_request(self, metadata, *, method_name, deadline,
                           content_type):
        return await self.__dispatch__(SendRequest(
            metadata=metadata,
            method_name=method_name,
            deadline=deadline,
            content_type=content_type,
        ))

    @_dispatches(RecvInitialMetadata)
    async def recv_initial_metadata(self, metadata):
        return await self.__dispatch__(RecvInitialMetadata(
            metadata=metadata,
        ))

    @_dispatches(RecvTrailingMetadata)
    async def recv_trailing_metadata(self, metadata):
        return await self.__dispatch__(RecvTrailingMetadata(
            metadata=metadata,
        ))
