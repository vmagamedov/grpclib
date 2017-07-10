from io import BytesIO
from abc import ABCMeta, abstractmethod
from asyncio import Transport, Protocol, Event, Queue

from h2.config import H2Configuration
from h2.events import RequestReceived, DataReceived, StreamEnded, WindowUpdated
from h2.events import ConnectionTerminated, RemoteSettingsChanged
from h2.events import SettingsAcknowledged, ResponseReceived, TrailersReceived
from h2.events import StreamReset, PriorityUpdated
from h2.connection import H2Connection
from h2.exceptions import ProtocolError


def _slice(chunks, size):
    first, first_size, second = [], 0, []
    for chunk in chunks:
        if first_size < size:
            if first_size + len(chunk) <= size:
                first.append(chunk)
            else:
                slice_size = size - first_size
                first.append(chunk[:slice_size])
                second.append(chunk[slice_size:])
        else:
            second.append(chunk)
    return first, second


class Buffer:

    def __init__(self, *, loop):
        self._chunks = []
        self._length = 0
        self._complete_size = -1
        self._complete_event = Event(loop=loop)

    def append(self, data):
        self._chunks.append(data)
        self._length += len(data)

        if self._complete_size != -1:
            if self._length >= self._complete_size:
                self._complete_event.set()

    def eof(self):
        self._complete_event.set()

    async def read(self, size=None):
        if size is None:
            await self._complete_event.wait()
            return b''.join(self._chunks)
        else:
            if size < 0:
                raise ValueError('Size is negative')
            elif size == 0:
                return b''
            else:
                if size > self._length:
                    self._complete_size = size
                    await self._complete_event.wait()
                    self._complete_size = -1
                    self._complete_event.clear()
                data, self._chunks = _slice(self._chunks, size)
                return b''.join(data)


class Stream:

    def __init__(self, write_ready, connection, transport, stream_id,
                 *, loop):
        self._write_ready = write_ready
        self._connection = connection
        self._transport = transport

        self.id = stream_id

        self.__buffer__ = Buffer(loop=loop)
        self.__headers__ = Queue(loop=loop)
        self.__window_updated__ = Event(loop=loop)

    async def recv_headers(self):
        return await self.__headers__.get()

    async def recv_data(self, size=None):
        data = await self.__buffer__.read(size)
        self._connection.acknowledge_received_data(len(data), self.id)
        return data

    async def send_headers(self, headers, end_stream=False):
        if not self._write_ready.is_set():
            await self._write_ready.wait()

        self._connection.send_headers(self.id, headers, end_stream=end_stream)
        self._transport.write(self._connection.data_to_send())

    async def send_data(self, data, end_stream=False):
        f = BytesIO(data)
        f_pos, f_last = 0, len(data)

        while True:
            if not self._write_ready.is_set():
                await self._write_ready.wait()

            window = self._connection.local_flow_control_window(self.id)
            if not window:
                self.__window_updated__.clear()
                await self.__window_updated__.wait()
                window = self._connection.local_flow_control_window(self.id)

            f_chunk = f.read(min(window, f_last - f_pos))
            f_pos = f.tell()

            if f_pos == f_last:
                self._connection.send_data(self.id, f_chunk,
                                           end_stream=end_stream)
                self._transport.write(self._connection.data_to_send())
                break
            else:
                self._connection.send_data(self.id, f_chunk)
                self._transport.write(self._connection.data_to_send())


class Request:

    def __init__(self, stream, headers):
        self.stream = stream
        self.headers = headers


class EventsProcessor:

    def __init__(self, handler, connection, transport, *, loop):
        self.handler = handler
        self.connection = connection
        self.transport = transport
        self.loop = loop

        self.handlers = {
            RequestReceived: self.handle_request_received,
            ResponseReceived: self.handle_response_received,
            RemoteSettingsChanged: self.handle_remote_settings_changed,
            SettingsAcknowledged: self.handle_settings_acknowledged,
            DataReceived: self.handle_data_received,
            WindowUpdated: self.handle_window_updated,
            TrailersReceived: self.handle_trailers_received,
            StreamEnded: self.handle_stream_ended,
            StreamReset: self.handle_stream_reset,
            PriorityUpdated: self.handle_priority_updated,
            ConnectionTerminated: self.handle_connection_terminated,
        }

        self.streams = {}  # TODO: streams cleanup
        self.write_ready = Event(loop=loop)

    @classmethod
    def init(cls, handler, config, transport, *, loop):
        connection = H2Connection(config=config)
        connection.initiate_connection()

        handler = cls(handler, connection, transport, loop=loop)
        handler.flush()
        return handler

    async def create_stream(self):
        # TODO: check concurrent streams count and maybe wait
        stream_id = self.connection.get_next_available_stream_id()
        stream = Stream(self.write_ready, self.connection, self.transport,
                        stream_id, loop=self.loop)
        self.streams[stream_id] = stream
        return stream

    def feed(self, data):
        return self.connection.receive_data(data)

    def flush(self):
        self.transport.write(self.connection.data_to_send())

    def close(self):
        self.transport.close()
        self.handler.close()

    def handle(self, event):
        try:
            handler = self.handlers[event.__class__]
        except KeyError:
            raise NotImplementedError(event)
        else:
            handler(event)

    def handle_request_received(self, event: RequestReceived):
        stream = Stream(self.write_ready, self.connection, self.transport,
                        event.stream_id, loop=self.loop)
        self.streams[event.stream_id] = stream
        self.handler.accept(stream, event.headers)
        # TODO: check EOF

    def handle_response_received(self, event: ResponseReceived):
        self.streams[event.stream_id].__headers__.put_nowait(event.headers)

    def handle_remote_settings_changed(self, event: RemoteSettingsChanged):
        pass

    def handle_settings_acknowledged(self, event: SettingsAcknowledged):
        pass

    def handle_data_received(self, event: DataReceived):
        self.streams[event.stream_id].__buffer__.append(event.data)

    def handle_window_updated(self, event: WindowUpdated):
        if event.stream_id > 0:
            self.streams[event.stream_id].__window_updated__.set()

    def handle_trailers_received(self, event: TrailersReceived):
        self.streams[event.stream_id].__headers__.put_nowait(event.headers)

    def handle_stream_ended(self, event: StreamEnded):
        self.streams[event.stream_id].__buffer__.eof()

    def handle_stream_reset(self, event: StreamReset):
        self.handler.cancel(self.streams[event.stream_id])

    def handle_priority_updated(self, event: PriorityUpdated):
        pass

    def handle_connection_terminated(self, event: ConnectionTerminated):
        self.close()


class H2Protocol(Protocol):
    processor = None

    def __init__(self, handler, config: H2Configuration, *, loop):
        self.handler = handler
        self.config = config
        self.loop = loop

    def connection_made(self, transport: Transport):
        self.processor = EventsProcessor.init(self.handler, self.config,
                                              transport, loop=self.loop)
        self.resume_writing()

    def data_received(self, data: bytes):
        try:
            events = self.processor.feed(data)
        except ProtocolError:
            self.processor.close()
        else:
            self.processor.flush()
            for event in events:
                self.processor.handle(event)
            self.processor.flush()

    def pause_writing(self):
        self.processor.write_ready.clear()

    def resume_writing(self):
        self.processor.write_ready.set()

    def connection_lost(self, exc):
        self.processor.close()


class AbstractHandler(metaclass=ABCMeta):

    @abstractmethod
    def accept(self, stream, headers):
        pass

    @abstractmethod
    def cancel(self, stream):
        pass

    @abstractmethod
    def close(self):
        pass


class NoHandler(AbstractHandler):

    def accept(self, stream, headers):
        raise NotImplementedError('Request handling is not implemented')

    def cancel(self, stream):
        pass

    def close(self):
        pass


class WrapProtocolMixin:

    def __init__(self, __obj, *args, **kwargs):
        self.__obj = __obj
        super().__init__(*args, **kwargs)

    def connection_made(self, transport):
        super().connection_made(transport)
        self.__obj.__connection_made__(self)

    def connection_lost(self, exc):
        super().connection_lost(exc)
        self.__obj.__connection_lost__(self)
