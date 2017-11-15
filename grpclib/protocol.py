import socket

from io import BytesIO
from abc import ABC, abstractmethod
from typing import Optional, List, Tuple, Dict  # noqa
from asyncio import Transport, Protocol, Event, Queue, AbstractEventLoop

from h2.errors import ErrorCodes
from h2.config import H2Configuration
from h2.events import RequestReceived, DataReceived, StreamEnded, WindowUpdated
from h2.events import ConnectionTerminated, RemoteSettingsChanged
from h2.events import SettingsAcknowledged, ResponseReceived, TrailersReceived
from h2.events import StreamReset, PriorityUpdated
from h2.settings import SettingCodes
from h2.connection import H2Connection
from h2.exceptions import ProtocolError, TooManyStreamsError


if hasattr(socket, 'TCP_NODELAY'):
    _sock_type_mask = 0xf if hasattr(socket, 'SOCK_NONBLOCK') else 0xffffffff

    def _set_nodelay(sock):
        if (
            sock.family in {socket.AF_INET, socket.AF_INET6}
            and sock.type & _sock_type_mask == socket.SOCK_STREAM
            and sock.proto == socket.IPPROTO_TCP
        ):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
else:
    def _set_nodelay(sock):
        pass


def _slice(chunks: List[bytes], size: int):
    data, data_size, tail = [], 0, []
    for chunk in chunks:
        if data_size < size:
            if data_size + len(chunk) <= size:
                data.append(chunk)
                data_size += len(chunk)
            else:
                slice_size = size - data_size
                data.append(chunk[:slice_size])
                tail.append(chunk[slice_size:])
                data_size += slice_size
        else:
            tail.append(chunk)
    return data, tail


class Buffer:

    def __init__(self, *, loop: AbstractEventLoop) -> None:
        self._chunks = []  # type: List[bytes]
        self._length = 0
        self._complete_size = -1
        self._complete_event = Event(loop=loop)
        self._eof = False

    def append(self, data):
        self._chunks.append(data)
        self._length += len(data)

        if self._complete_size != -1:
            if self._length >= self._complete_size:
                self._complete_event.set()

    def eof(self):
        self._eof = True
        self._complete_event.set()

    async def read(self, size=None):
        if size is None:
            if not self._eof:
                await self._complete_event.wait()
            return b''.join(self._chunks)
        else:
            if size < 0:
                raise ValueError('Size is negative')
            elif size == 0:
                return b''
            else:
                if size > self._length and not self._eof:
                    self._complete_size = size
                    await self._complete_event.wait()
                    self._complete_size = -1
                    self._complete_event.clear()
                data, self._chunks = _slice(self._chunks, size)
                self._length -= size
                data_bytes = b''.join(data)
                if data_bytes and len(data_bytes) < size:
                    # TODO: proper exception
                    raise Exception('Incomplete data, {} instead of {}'
                                    .format(len(data_bytes), size))
                return data_bytes


class StreamsLimit:

    def __init__(self, limit=None, *, loop):
        self._limit = limit
        self._current = 0
        self._loop = loop
        self._release = Event(loop=loop)

    def reached(self):
        if self._limit is not None:
            return self._current >= self._limit
        else:
            return False

    async def wait(self):
        # TODO: use FIFO queue for waiters
        if self.reached():
            self._release.clear()
        await self._release.wait()

    def acquire(self):
        self._current += 1

    def release(self):
        self._current -= 1
        if not self.reached():
            self._release.set()

    def set(self, value: Optional[int]):
        assert value is None or value >= 0, value
        self._limit = value


class Connection:
    """
    Holds connection state (write_ready), and manages
    H2Connection <-> Transport communication
    """
    def __init__(self, connection: H2Connection, transport: Transport,
                 *, loop: AbstractEventLoop) -> None:
        self._connection = connection
        self._transport = transport
        self._loop = loop

        self.write_ready = Event(loop=self._loop)
        self.write_ready.set()

        self.outbound_streams_limit = StreamsLimit(loop=self._loop)

    def feed(self, data):
        return self._connection.receive_data(data)

    def pause_writing(self):
        self.write_ready.clear()

    def resume_writing(self):
        self.write_ready.set()

    def create_stream(self, stream_id=None):
        return Stream(self, self._connection, self._transport, stream_id,
                      loop=self._loop)

    def flush(self):
        self._transport.write(self._connection.data_to_send())

    def close(self):
        self._transport.close()


class Stream:
    """
    API for working with streams, used by clients and request handlers
    """
    def __init__(self, connection: Connection, h2_connection: H2Connection,
                 transport: Transport, stream_id: Optional[int] = None,
                 *, loop: AbstractEventLoop) -> None:
        self._connection = connection
        self._h2_connection = h2_connection
        self._transport = transport

        self.id = stream_id

        self.__buffer__ = Buffer(loop=loop)
        self.__headers__ = Queue(loop=loop) \
            # type: Queue[List[Tuple[str, str]]]
        self.__window_updated__ = Event(loop=loop)

    async def recv_headers(self):
        return await self.__headers__.get()

    async def recv_data(self, size=None):
        data = await self.__buffer__.read(size)
        self._h2_connection.acknowledge_received_data(len(data), self.id)
        return data

    async def send_request(self, headers, end_stream=False, *, _processor):
        assert self.id is None, self.id
        while True:
            # this is the first thing we should check before even trying to
            # create new stream, because this wait() can be cancelled by timeout
            # and we wouldn't need to create new stream at all
            if not self._connection.write_ready.is_set():
                await self._connection.write_ready.wait()

            if self._connection.outbound_streams_limit.reached():
                await self._connection.outbound_streams_limit.wait()
                # while we were trying to create a new stream, write buffer
                # can became full, so we need to repeat checks from checking
                # if we can write() data
                continue

            # `get_next_available_stream_id()` should be as close to
            # `connection.send_headers()` as possible, without any async
            # interruptions in between, see the docs on the
            # `get_next_available_stream_id()` method
            stream_id = self._h2_connection.get_next_available_stream_id()
            try:
                self._h2_connection.send_headers(stream_id, headers,
                                                 end_stream=end_stream)
            except TooManyStreamsError:
                continue
            else:
                self._connection.outbound_streams_limit.acquire()
                self.id = stream_id
                _processor.register(self)
                self._transport.write(self._h2_connection.data_to_send())
                break

    async def send_headers(self, headers, end_stream=False):
        assert self.id is not None
        if not self._connection.write_ready.is_set():
            await self._connection.write_ready.wait()

        self._h2_connection.send_headers(self.id, headers,
                                         end_stream=end_stream)
        self._transport.write(self._h2_connection.data_to_send())

    async def send_data(self, data, end_stream=False):
        f = BytesIO(data)
        f_pos, f_last = 0, len(data)

        while True:
            if not self._connection.write_ready.is_set():
                await self._connection.write_ready.wait()

            window = self._h2_connection.local_flow_control_window(self.id)
            if not window:
                self.__window_updated__.clear()
                await self.__window_updated__.wait()
                window = self._h2_connection.local_flow_control_window(self.id)

            f_chunk = f.read(min(window, f_last - f_pos))
            f_pos = f.tell()

            if f_pos == f_last:
                self._h2_connection.send_data(self.id, f_chunk,
                                              end_stream=end_stream)
                self._transport.write(self._h2_connection.data_to_send())
                break
            else:
                self._h2_connection.send_data(self.id, f_chunk)
                self._transport.write(self._h2_connection.data_to_send())

    async def end(self):
        if not self._connection.write_ready.is_set():
            await self._connection.write_ready.wait()
        self._h2_connection.end_stream(self.id)
        self._transport.write(self._h2_connection.data_to_send())

    async def reset(self, error_code=ErrorCodes.NO_ERROR):
        if not self._connection.write_ready.is_set():
            await self._connection.write_ready.wait()
        self._h2_connection.reset_stream(self.id, error_code=error_code)
        self._transport.write(self._h2_connection.data_to_send())

    def __ended__(self):
        self.__buffer__.eof()


class AbstractHandler(ABC):

    @abstractmethod
    def accept(self, stream, headers):
        pass

    @abstractmethod
    def cancel(self, stream):
        pass

    @abstractmethod
    def close(self):
        pass


class EventsProcessor:
    """
    H2 events processor, synchronous, not doing any IO, as hyper-h2 itself
    """
    def __init__(self, handler: AbstractHandler,
                 connection: Connection) -> None:
        self.handler = handler
        self.connection = connection

        self.processors = {
            RequestReceived: self.process_request_received,
            ResponseReceived: self.process_response_received,
            RemoteSettingsChanged: self.process_remote_settings_changed,
            SettingsAcknowledged: self.process_settings_acknowledged,
            DataReceived: self.process_data_received,
            WindowUpdated: self.process_window_updated,
            TrailersReceived: self.process_trailers_received,
            StreamEnded: self.process_stream_ended,
            StreamReset: self.process_stream_reset,
            PriorityUpdated: self.process_priority_updated,
            ConnectionTerminated: self.process_connection_terminated,
        }

        self.streams = {}  # type: Dict[int, Stream]

    def create_stream(self):
        stream = self.connection.create_stream()
        self.streams[stream.id] = stream
        return stream

    def register(self, stream):
        assert stream.id is not None
        self.streams[stream.id] = stream

    def close(self):
        self.connection.close()
        self.handler.close()

    def process(self, event):
        try:
            proc = self.processors[event.__class__]
        except KeyError:
            raise NotImplementedError(event)
        else:
            proc(event)

    def process_request_received(self, event: RequestReceived):
        stream = self.connection.create_stream(event.stream_id)
        self.streams[event.stream_id] = stream
        self.handler.accept(stream, event.headers)
        # TODO: check EOF

    def process_response_received(self, event: ResponseReceived):
        self.streams[event.stream_id].__headers__.put_nowait(event.headers)

    def process_remote_settings_changed(self, event: RemoteSettingsChanged):
        if SettingCodes.MAX_CONCURRENT_STREAMS in event.changed_settings:
            max_concurrent_streams = \
                event.changed_settings[SettingCodes.MAX_CONCURRENT_STREAMS]
            self.connection.outbound_streams_limit.set(max_concurrent_streams
                                                       .new_value)

    def process_settings_acknowledged(self, event: SettingsAcknowledged):
        pass

    def process_data_received(self, event: DataReceived):
        self.streams[event.stream_id].__buffer__.append(event.data)

    def process_window_updated(self, event: WindowUpdated):
        if event.stream_id > 0:
            self.streams[event.stream_id].__window_updated__.set()

    def process_trailers_received(self, event: TrailersReceived):
        self.streams[event.stream_id].__headers__.put_nowait(event.headers)

    def process_stream_ended(self, event: StreamEnded):
        self.streams.pop(event.stream_id).__ended__()
        self.connection.outbound_streams_limit.release()

    def process_stream_reset(self, event: StreamReset):
        stream = self.streams.pop(event.stream_id)
        self.handler.cancel(stream)

    def process_priority_updated(self, event: PriorityUpdated):
        pass

    def process_connection_terminated(self, event: ConnectionTerminated):
        self.close()


class H2Protocol(Protocol):
    connection = None  # type: Optional[Connection]
    processor = None  # type: Optional[EventsProcessor]

    def __init__(self, handler: AbstractHandler, config: H2Configuration,
                 *, loop) -> None:
        self.handler = handler
        self.config = config
        self.loop = loop

    def connection_made(self, transport: Transport):  # type: ignore
        sock = transport.get_extra_info('socket')
        if sock is not None:
            _set_nodelay(sock)

        h2_conn = H2Connection(config=self.config)
        h2_conn.initiate_connection()

        self.connection = Connection(h2_conn, transport, loop=self.loop)
        self.connection.flush()

        self.processor = EventsProcessor(self.handler, self.connection)

    def data_received(self, data: bytes):
        try:
            events = self.connection.feed(data)
        except ProtocolError:
            self.processor.close()
        else:
            self.connection.flush()
            for event in events:
                self.processor.process(event)
            self.connection.flush()

    def pause_writing(self):
        self.connection.pause_writing()

    def resume_writing(self):
        self.connection.resume_writing()

    def connection_lost(self, exc):
        self.processor.close()
