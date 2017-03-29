import asyncio

import aioh2


class H2Protocol(aioh2.H2Protocol):
    _handler_task = None

    def __init__(self, handler, mapping, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._handler = handler
        self._mapping = mapping

    def connection_made(self, transport):
        super().connection_made(transport)
        self._handler_task = self._loop.create_task(
            self._handler(self, self._mapping, loop=self._loop)
        )

    def connection_lost(self, exc):
        super().connection_lost(exc)
        self._handler_task.cancel()

    async def shutdown(self):
        if self._handler_task.cancel():
            try:
                await self._handler_task
            except asyncio.CancelledError:
                pass
