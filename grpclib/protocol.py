import socket
import typing

from io import BytesIO
from abc import ABC, abstractmethod
from typing import Optional, List, Tuple, Dict  # noqa
from asyncio import Transport, Protocol, Event, AbstractEventLoop
from asyncio import Queue, QueueEmpty
from functools import partial
from collections import deque

from h2.errors import ErrorCodes
from h2.config import H2Configuration
from h2.events import RequestReceived, DataReceived, StreamEnded, WindowUpdated
from h2.events import ConnectionTerminated, RemoteSettingsChanged
from h2.events import SettingsAcknowledged, ResponseReceived, TrailersReceived
from h2.events import StreamReset, PriorityUpdated, PingAcknowledged
from h2.settings import SettingCodes
from h2.connection import H2Connection, ConnectionState
from h2.exceptions import ProtocolError, TooManyStreamsError, StreamClosedError

from .utils import Wrapper
from .exceptions import StreamTerminatedError


try:
    from h2.events import PingReceived, PingAckReceived
except ImportError:
    PingReceived = object()
    PingAckReceived = object()


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


class UnackedData(typing.NamedTuple):
    data: bytes
    data_size: int
    ack_size: int


class AckedData(typing.NamedTuple):
    data: memoryview
    data_size: int


class Buffer:

    def __init__(self, ack_callback, *, loop):
        self._ack_callback = ack_callback
        self._eof = False
        self._unacked = Queue(loop=loop)
        self._acked = deque()
        self._acked_size = 0

    def add(self, data, ack_size):
        self._unacked.put_nowait(UnackedData(data, len(data), ack_size))

    def eof(self):
        self._unacked.put_nowait(UnackedData(b'', 0, 0))
        self._eof = True

    async def read(self, size):
        assert size >= 0, 'Size can not be negative'
        if size == 0:
            return b''

        if not self._eof or not self._unacked.empty():
            while self._acked_size < size:
                data, data_size, ack_size = await self._unacked.get()
                if not ack_size:
                    break
                self._acked.append(AckedData(memoryview(data), data_size))
                self._acked_size += data_size
                self._ack_callback(ack_size)

        if self._eof and self._acked_size == 0:
            return b''

        if self._acked_size < size:
            raise AssertionError('Received less data than expected')

        chunks = []
        chunks_size = 0
        while chunks_size < size:
            next_chunk, next_chunk_size = self._acked[0]
            if chunks_size + next_chunk_size <= size:
                chunks.append(next_chunk)
                chunks_size += next_chunk_size
                self._acked.popleft()
            else:
                offset = size - chunks_size
                chunks.append(next_chunk[:offset])
                chunks_size += offset
                self._acked[0] = (next_chunk[offset:], next_chunk_size - offset)
        self._acked_size -= size
        assert chunks_size == size
        return b''.join(chunks)

    def unacked_size(self):
        return sum(self._unacked.get_nowait().ack_size
                   for _ in range(self._unacked.qsize()))


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
    _transport = None

    def __init__(self, connection: H2Connection, transport: Transport,
                 *, loop: AbstractEventLoop) -> None:
        self._connection = connection
        self._transport = transport
        self._loop = loop

        self.write_ready = Event(loop=self._loop)
        self.write_ready.set()

        self.stream_close_waiter = Event(loop=self._loop)

    def feed(self, data):
        return self._connection.receive_data(data)

    def ack(self, stream_id, size):
        if size:
            self._connection.acknowledge_received_data(size, stream_id)
            self.flush()

    def pause_writing(self):
        self.write_ready.clear()

    def resume_writing(self):
        self.write_ready.set()

    def create_stream(self, *, stream_id=None, wrapper=None):
        return Stream(self, self._connection, self._transport, loop=self._loop,
                      stream_id=stream_id, wrapper=wrapper)

    def flush(self):
        data = self._connection.data_to_send()
        if data:
            self._transport.write(data)

    def close(self):
        if self._transport:
            self._transport.close()
            # remove cyclic references to improve memory usage
            del self._transport
            if hasattr(self._connection, '_frame_dispatch_table'):
                del self._connection._frame_dispatch_table


class Stream:
    """
    API for working with streams, used by clients and request handlers
    """
    id = None
    __buffer__ = None
    __wrapper__ = None

    def __init__(
        self, connection: Connection, h2_connection: H2Connection,
        transport: Transport, *, loop: AbstractEventLoop,
        stream_id: Optional[int] = None,
        wrapper: Optional[Wrapper] = None
    ) -> None:
        self._connection = connection
        self._h2_connection = h2_connection
        self._transport = transport
        self._loop = loop
        self.__wrapper__ = wrapper

        if stream_id is not None:
            self.init_stream(stream_id, self._connection, loop=self._loop)

        self.__headers__ = Queue(loop=loop) \
            # type: Queue[List[Tuple[str, str]]]
        self.__window_updated__ = Event(loop=loop)

    def init_stream(self, stream_id, connection, *, loop):
        self.id = stream_id
        self.__buffer__ = Buffer(partial(connection.ack, self.id),
                                 loop=loop)

    async def recv_headers(self):
        return await self.__headers__.get()

    def recv_headers_nowait(self):
        try:
            return self.__headers__.get_nowait()
        except QueueEmpty:
            return None

    async def recv_data(self, size):
        return await self.__buffer__.read(size)

    async def send_request(self, headers, end_stream=False, *, _processor):
        assert self.id is None, self.id
        while True:
            # this is the first thing we should check before even trying to
            # create new stream, because this wait() can be cancelled by timeout
            # and we wouldn't need to create new stream at all
            if not self._connection.write_ready.is_set():
                await self._connection.write_ready.wait()

            # `get_next_available_stream_id()` should be as close to
            # `connection.send_headers()` as possible, without any async
            # interruptions in between, see the docs on the
            # `get_next_available_stream_id()` method
            stream_id = self._h2_connection.get_next_available_stream_id()
            try:
                self._h2_connection.send_headers(stream_id, headers,
                                                 end_stream=end_stream)
            except TooManyStreamsError:
                # we're going to wait until any of currently opened streams will
                # be closed, and we will be able to open a new one
                # TODO: maybe implement FIFO for waiters, but this limit
                #       shouldn't be reached in a normal case, so why bother
                # TODO: maybe we should raise an exception here instead of
                #       waiting, if timeout wasn't set for the current request
                self._connection.stream_close_waiter.clear()
                await self._connection.stream_close_waiter.wait()
                # while we were trying to create a new stream, write buffer
                # can became full, so we need to repeat checks from checking
                # if we can write() data
                continue
            else:
                self.init_stream(stream_id, self._connection, loop=self._loop)
                release_stream = _processor.register(self)
                self._transport.write(self._h2_connection.data_to_send())
                return release_stream

    async def send_headers(self, headers, end_stream=False):
        assert self.id is not None
        if not self._connection.write_ready.is_set():
            await self._connection.write_ready.wait()

        # Workaround for the H2Connection.send_headers method, which will try
        # to create a new stream if it was removed earlier from the
        # H2Connection.streams, and therefore will raise StreamIDTooLowError
        if self.id not in self._h2_connection.streams:
            raise StreamClosedError(self.id)

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

            max_frame_size = self._h2_connection.max_outbound_frame_size
            f_chunk = f.read(min(window, max_frame_size, f_last - f_pos))
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

    def reset_nowait(self, error_code=ErrorCodes.NO_ERROR):
        self._h2_connection.reset_stream(self.id, error_code=error_code)
        if self._connection.write_ready.is_set():
            self._transport.write(self._h2_connection.data_to_send())

    def __ended__(self):
        self.__buffer__.eof()

    def __terminated__(self, reason):
        if self.__wrapper__ is not None:
            self.__wrapper__.cancel(StreamTerminatedError(reason))

    @property
    def closable(self):
        if self._h2_connection.state_machine.state is ConnectionState.CLOSED:
            return False
        stream = self._h2_connection.streams.get(self.id)
        if stream is None:
            return False
        return not stream.closed


class AbstractHandler(ABC):

    @abstractmethod
    def accept(self, stream, headers, release_stream):
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
            PingReceived: self.process_ping_received,
            PingAckReceived: self.process_ping_ack_received,
            PingAcknowledged: self.process_ping_ack_received,  # deprecated
        }

        self.streams = {}  # type: Dict[int, Stream]

    def create_stream(self):
        stream = self.connection.create_stream()
        self.streams[stream.id] = stream
        return stream

    def register(self, stream):
        assert stream.id is not None
        self.streams[stream.id] = stream

        def release_stream(*, _streams=self.streams, _id=stream.id):
            _stream = _streams.pop(_id)
            self.connection.stream_close_waiter.set()
            self.connection.ack(_id, _stream.__buffer__.unacked_size())

        return release_stream

    def close(self):
        self.connection.close()
        self.handler.close()
        for stream in self.streams.values():
            stream.__terminated__('Connection was closed')
        # remove cyclic references to improve memory usage
        if hasattr(self, 'processors'):
            del self.processors

    def process(self, event):
        try:
            proc = self.processors[event.__class__]
        except KeyError:
            raise NotImplementedError(event)
        else:
            proc(event)

    def process_request_received(self, event: RequestReceived):
        stream = self.connection.create_stream(stream_id=event.stream_id)
        release_stream = self.register(stream)
        self.handler.accept(stream, event.headers, release_stream)
        # TODO: check EOF

    def process_response_received(self, event: ResponseReceived):
        stream = self.streams.get(event.stream_id)
        if stream is not None:
            stream.__headers__.put_nowait(event.headers)

    def process_remote_settings_changed(self, event: RemoteSettingsChanged):
        if SettingCodes.INITIAL_WINDOW_SIZE in event.changed_settings:
            for stream in self.streams.values():
                stream.__window_updated__.set()

    def process_settings_acknowledged(self, event: SettingsAcknowledged):
        pass

    def process_data_received(self, event: DataReceived):
        stream = self.streams.get(event.stream_id)
        if stream is not None:
            stream.__buffer__.add(
                event.data,
                event.flow_controlled_length,
            )
        else:
            self.connection.ack(
                event.stream_id,
                event.flow_controlled_length,
            )

    def process_window_updated(self, event: WindowUpdated):
        if event.stream_id == 0:
            for stream in self.streams.values():
                stream.__window_updated__.set()
        else:
            stream = self.streams.get(event.stream_id)
            if stream is not None:
                stream.__window_updated__.set()

    def process_trailers_received(self, event: TrailersReceived):
        stream = self.streams.get(event.stream_id)
        if stream is not None:
            stream.__headers__.put_nowait(event.headers)

    def process_stream_ended(self, event: StreamEnded):
        stream = self.streams.get(event.stream_id)
        if stream is not None:
            stream.__ended__()

    def process_stream_reset(self, event: StreamReset):
        stream = self.streams.get(event.stream_id)
        if stream is not None:
            if event.remote_reset:
                msg = ('Stream reset by remote party, error_code: {}'
                       .format(event.error_code))
            else:
                msg = 'Protocol error'
            stream.__terminated__(msg)
            self.handler.cancel(stream)

    def process_priority_updated(self, event: PriorityUpdated):
        pass

    def process_connection_terminated(self, event: ConnectionTerminated):
        self.close()

    def process_ping_received(self, event: PingReceived):
        pass

    def process_ping_ack_received(self, event: PingAckReceived):
        pass


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
