import asyncio

from grpclib.protocol import AbstractHandler


class TransportStub(asyncio.Transport):

    def __init__(self, connection):
        super().__init__()
        self._connection = connection
        self._events = []
        self._error = None

    def __raise_on_write__(self, exc_type):
        self._error = exc_type

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
        if self._error is not None:
            exc = self._error()
            self._error = None
            raise exc
        else:
            self._events.extend(self._connection.receive_data(data))


class DummyHandler(AbstractHandler):
    stream = None
    headers = None
    release_stream = None

    def accept(self, stream, headers, release_stream):
        self.stream = stream
        self.headers = headers
        self.release_stream = release_stream

    def cancel(self, stream):
        pass

    def close(self):
        pass
