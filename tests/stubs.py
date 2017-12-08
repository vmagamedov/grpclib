import asyncio

from grpclib.protocol import AbstractHandler


class TransportStub(asyncio.Transport):

    def __init__(self, connection):
        super().__init__()
        self._connection = connection
        self._events = []

    def events(self):
        events = self._events[:]
        del self._events[:]
        return events

    def process(self, processor):
        events = self.events()
        for event in events:
            processor.process(event)
        return events

    def write(self, data):
        self._events.extend(self._connection.receive_data(data))


class DummyHandler(AbstractHandler):
    release_stream = None

    def accept(self, stream, headers, release_stream):
        self.release_stream = release_stream

    def cancel(self, stream):
        pass

    def close(self):
        pass
