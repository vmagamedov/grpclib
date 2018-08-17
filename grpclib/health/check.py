import abc
import time
import asyncio
import logging

from ..utils import DeadlineWrapper
from ..metadata import Deadline


log = logging.getLogger(__name__)

DEFAULT_CHECK_TTL = 30
DEFAULT_CHECK_TIMEOUT = 10


class CheckBase(abc.ABC):

    @abc.abstractmethod
    def __status__(self):
        pass

    @abc.abstractmethod
    async def __check__(self):
        pass

    @abc.abstractmethod
    async def __subscribe__(self):
        pass

    @abc.abstractmethod
    async def __unsubscribe__(self, event):
        pass


class ServiceCheck(CheckBase):
    _value = None
    _poll_task = None
    _last_check = 0.0

    def __init__(self, *, loop, check_ttl=DEFAULT_CHECK_TTL,
                 check_timeout=DEFAULT_CHECK_TIMEOUT):
        self._check_ttl = check_ttl
        self._check_timeout = check_timeout

        self._events = set()

        self._check_lock = asyncio.Event(loop=loop)
        self._check_lock.set()

        self._check_wrapper = DeadlineWrapper()

    @abc.abstractmethod
    async def check(self):
        pass

    def __status__(self):
        return self._value

    async def __check__(self):
        if time.monotonic() - self._last_check < self._check_ttl:
            return self._value

        if not self._check_lock.is_set():
            # wait until concurrent check succeed
            await self._check_lock.wait()
            return self._value

        self._check_lock.clear()
        try:
            deadline = Deadline.from_timeout(self._check_timeout)
            with self._check_wrapper.start(deadline):
                self._value = await self.check()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('Health check failed')
            self._value = False
        finally:
            self._check_lock.set()

        self._last_check = time.monotonic()
        # notify all watchers that this check was changed
        for event in self._events:
            event.set()
        return self._value

    async def _poll(self):
        while True:
            status = await self.__check__()
            if status:
                await asyncio.sleep(self._check_ttl)
            else:
                await asyncio.sleep(self._check_ttl)  # TODO: change interval?

    async def __subscribe__(self):
        if self._poll_task is None:
            loop = asyncio.get_event_loop()
            self._poll_task = loop.create_task(self._poll())

        event = asyncio.Event()
        self._events.add(event)
        return event

    async def __unsubscribe__(self, event):
        self._events.discard(event)

        if not self._events:
            task = self._poll_task
            self._poll_task = None
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class ServiceStatus(CheckBase):

    def __init__(self):
        self._value = None
        self._events = set()

    def set(self, value: bool):
        self._value = value
        # notify all watchers that this check was changed
        for event in self._events:
            event.set()

    def __status__(self):
        return self._value

    async def __check__(self):
        return self._value

    async def __subscribe__(self):
        event = asyncio.Event()
        self._events.add(event)
        return event

    async def __unsubscribe__(self, event):
        self._events.discard(event)
