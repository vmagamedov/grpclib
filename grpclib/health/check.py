import abc
import time
import asyncio
import logging


log = logging.getLogger(__name__)

DEFAULT_CHECK_TTL = 30


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
    _poll_task = None

    def __init__(self, *, ttl=DEFAULT_CHECK_TTL):
        self._value = None
        self._ttl = ttl
        self._last_check = 0.0
        self._events = set()

    @abc.abstractmethod
    async def check(self):
        pass

    def __status__(self):
        return self._value

    async def __check__(self):
        if time.monotonic() - self._last_check > self._ttl:
            try:
                self._value = await self.check()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('Health check failed')
                self._value = False
            self._last_check = time.monotonic()
            # notify all watchers that this check was changed
            for event in self._events:
                event.set()
        return self._value

    async def _poll(self):
        while True:
            status = await self.__check__()
            if status:
                await asyncio.sleep(self._ttl)
            else:
                await asyncio.sleep(self._ttl)  # TODO: change interval?

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
