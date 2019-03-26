import socket

from io import BytesIO
from abc import ABC, abstractmethod
from typing import Optional, List, Tuple, Dict, Iterable, Callable, Type, Any # noqa
from asyncio import Protocol, Event, AbstractEventLoop, WriteTransport, BaseTransport
from asyncio import Queue, QueueEmpty

from h2.errors import ErrorCodes
from h2.config import H2Configuration
from h2.events import RequestReceived, DataReceived, StreamEnded, WindowUpdated
from h2.events import ConnectionTerminated, RemoteSettingsChanged
from h2.events import SettingsAcknowledged, ResponseReceived, TrailersReceived
from h2.events import StreamReset, PriorityUpdated, PingAcknowledged
from h2.settings import SettingCodes
from h2.connection import H2Connection, ConnectionState
from h2.exceptions import ProtocolError, TooManyStreamsError, StreamClosedError

from .utils import Wrapper, none_throws
from .exceptions import StreamTerminatedError


try:
    from h2.events import PingReceived, PingAckReceived
except ImportError:
    PingReceived = object()  # type: ignore
    PingAckReceived = object()  # type: ignore


if hasattr(socket, 'TCP_NODELAY'):
    _sock_type_mask = 0xf if hasattr(socket, 'SOCK_NONBLOCK') else 0xffffffff

    def _set_nodelay(sock: socket.socket) -> None:
        if (
            sock.family in {socket.AF_INET, socket.AF_INET6}
            and sock.type & _sock_type_mask == socket.SOCK_STREAM
            and sock.proto == socket.IPPROTO_TCP
        ):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
else:
    def _set_nodelay(sock: socket.socket) -> None:
        pass


def _slice(chunks: Iterable[bytes], size: int) -> Tuple[List[bytes], List[bytes]]:
    data = []  # type: List[bytes]
    data_size = 0  # type: int
    tail = []  # type: List[bytes]
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

    def __init__(
        self,
        stream_id: int,
        connection: "Connection",
        h2_connection: H2Connection,
        *,
        loop: AbstractEventLoop,
    ) -> None:
        self._stream_id = stream_id
        self._connection = connection
        self._h2_connection = h2_connection
        self._chunks = []  # type: List[bytes]
        self._size = 0
        self._read_size = None  # type: Optional[int]
        self._ready_event = Event(loop=loop)
        self._eof = False

    def _ack(self, size: int) -> None:
        if size:
            self._h2_connection.acknowledge_received_data(size, self._stream_id)
            self._connection.flush()

    def append(self, data: bytes) -> None:
        size = len(data)
        self._chunks.append(data)
        self._size += size

        if self._read_size is not None:
            self._ack(min(max(size - self._size + self._read_size, 0), size))
            if self._size >= self._read_size:
                self._ready_event.set()

    def eof(self) -> None:
        self._eof = True
        self._ready_event.set()

    async def read(self, size: int) -> bytes:
        if size < 0:
            raise ValueError('Size can not be negative')
        elif size == 0:
            return b''
        else:
            if self._size < size and not self._eof:
                self._read_size = size
                self._ready_event.clear()
                self._ack(self._size)
                await self._ready_event.wait()
                self._read_size = None
            elif self._size >= size:
                self._ack(size)
            else:
                assert self._eof
                self._ack(self._size)

            data, self._chunks = _slice(self._chunks, size)
            data_bytes = b''.join(data)
            data_size = len(data_bytes)
            self._size -= data_size

            if 0 < data_size < size:
                # TODO: proper exception
                raise Exception('Incomplete data, {} instead of {}'
                                .format(data_size, size))
            return data_bytes


class StreamsLimit:

    def __init__(self, limit: Optional[int] = None, *, loop: AbstractEventLoop) -> None:
        self._limit = limit
        self._current = 0
        self._loop = loop
        self._release = Event(loop=loop)

    def reached(self) -> bool:
        if self._limit is not None:
            return self._current >= self._limit
        else:
            return False

    async def wait(self) -> None:
        # TODO: use FIFO queue for waiters
        if self.reached():
            self._release.clear()
        await self._release.wait()

    def acquire(self) -> None:
        self._current += 1

    def release(self) -> None:
        self._current -= 1
        if not self.reached():
            self._release.set()

    def set(self, value: Optional[int]) -> None:
        assert value is None or value >= 0, value
        self._limit = value


class Connection:
    """
    Holds connection state (write_ready), and manages
    H2Connection <-> Transport communication
    """
    def __init__(self, connection: H2Connection, transport: WriteTransport,
                 *, loop: AbstractEventLoop) -> None:
        self._connection = connection
        self._transport = transport
        self._loop = loop

        self.write_ready = Event(loop=self._loop)
        self.write_ready.set()

        self.stream_close_waiter = Event(loop=self._loop)

    def feed(self, data: bytes) -> List[Event]:
        return self._connection.receive_data(data)

    def pause_writing(self) -> None:
        self.write_ready.clear()

    def resume_writing(self) -> None:
        self.write_ready.set()

    def create_stream(
        self,
        *,
        stream_id: Optional[int] = None,
        wrapper: Optional[Wrapper] = None,
    ) -> "Stream":
        return Stream(self, self._connection, self._transport, loop=self._loop,
                      stream_id=stream_id, wrapper=wrapper)

    def flush(self) -> None:
        data = self._connection.data_to_send()
        if data:
            self._transport.write(data)

    def close(self) -> None:
        self._transport.close()


class Stream:
    """
    API for working with streams, used by clients and request handlers
    """
    id = None
    __buffer__ = None
    __wrapper__ = None

    def __init__(
        self, connection: "Connection", h2_connection: H2Connection,
        transport: WriteTransport, *, loop: AbstractEventLoop,
        stream_id: Optional[int] = None,
        wrapper: Optional[Wrapper] = None,
    ) -> None:
        self._connection = connection
        self._h2_connection = h2_connection
        self._transport = transport
        self._loop = loop
        self.__wrapper__ = wrapper

        if stream_id is not None:
            self.id = stream_id
            self.__buffer__ = Buffer(self.id, self._connection,
                                     self._h2_connection, loop=self._loop)

        self.__headers__ = Queue(loop=loop)  # type: Queue[List[Tuple[str, str]]]
        self.__window_updated__ = Event(loop=loop)

    async def recv_headers(self) -> List[Tuple[str, str]]:
        return await self.__headers__.get()

    def recv_headers_nowait(self) -> Optional[List[Tuple[str, str]]]:
        try:
            return self.__headers__.get_nowait()
        except QueueEmpty:
            return None

    async def recv_data(self, size: int) -> bytes:
        return await none_throws(self.__buffer__).read(size)

    async def send_request(self, headers: List[Tuple[str, str]], end_stream: bool = False, *, _processor) -> "Stream":
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
                self.id = stream_id
                self.__buffer__ = Buffer(self.id, self._connection,
                                         self._h2_connection, loop=self._loop)
                release_stream = _processor.register(self)
                self._transport.write(self._h2_connection.data_to_send())
                return release_stream

    async def send_headers(self, headers: List[Tuple[str, str]], end_stream: bool = False) -> None:
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

    async def send_data(self, data: bytes, end_stream: bool = False) -> None:
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

    async def end(self) -> None:
        if not self._connection.write_ready.is_set():
            await self._connection.write_ready.wait()
        self._h2_connection.end_stream(self.id)
        self._transport.write(self._h2_connection.data_to_send())

    async def reset(self, error_code: ErrorCodes = ErrorCodes.NO_ERROR) -> None:
        if not self._connection.write_ready.is_set():
            await self._connection.write_ready.wait()
        self._h2_connection.reset_stream(self.id, error_code=error_code)
        self._transport.write(self._h2_connection.data_to_send())

    def reset_nowait(self, error_code: ErrorCodes = ErrorCodes.NO_ERROR) -> None:
        self._h2_connection.reset_stream(self.id, error_code=error_code)
        if self._connection.write_ready.is_set():
            self._transport.write(self._h2_connection.data_to_send())

    def __ended__(self) -> None:
        none_throws(self.__buffer__).eof()

    def __terminated__(self, reason: str) -> None:
        if self.__wrapper__ is not None:
            self.__wrapper__.cancel(StreamTerminatedError(reason))

    @property
    def closable(self) -> bool:
        if self._h2_connection.state_machine.state is ConnectionState.CLOSED:
            return False
        stream = self._h2_connection.streams.get(self.id)
        if stream is None:
            return False
        return not stream.closed


class AbstractHandler(ABC):

    @abstractmethod
    def accept(self, stream: Stream, headers: List[Tuple[str, str]], release_stream: Callable[[], None]) -> None:
        pass

    @abstractmethod
    def cancel(self, stream: Stream) -> None:
        pass

    @abstractmethod
    def close(self) -> None:
        pass


class EventsProcessor:
    """
    H2 events processor, synchronous, not doing any IO, as hyper-h2 itself
    """
    def __init__(self, handler: AbstractHandler,
                 connection: Connection) -> None:
        self.handler = handler
        self.connection = connection

        self.processors = {  # type: Dict[Type[Any], Callable[[Any], None]]
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

    def create_stream(self) -> Stream:
        stream = self.connection.create_stream()
        self.streams[none_throws(stream.id)] = stream
        return stream

    def register(self, stream: Stream) -> Callable[[], None]:
        self.streams[none_throws(stream.id)] = stream

        def release_stream(
            *,
            _streams: Dict[int, Stream] = self.streams,
            _id: int = none_throws(stream.id),
        ) -> None:
            _streams.pop(_id)
            self.connection.stream_close_waiter.set()

        return release_stream

    def close(self) -> None:
        self.connection.close()
        self.handler.close()
        for stream in self.streams.values():
            stream.__terminated__('Connection was closed')

    def process(self, event: Event) -> None:
        try:
            proc = self.processors[event.__class__]
        except KeyError:
            raise NotImplementedError(event)
        else:
            proc(event)

    def process_request_received(self, event: RequestReceived) -> None:
        stream = self.connection.create_stream(stream_id=event.stream_id)
        release_stream = self.register(stream)
        self.handler.accept(stream, event.headers, release_stream)
        # TODO: check EOF

    def process_response_received(self, event: ResponseReceived) -> None:
        stream = self.streams.get(event.stream_id)
        if stream is not None:
            stream.__headers__.put_nowait(event.headers)

    def process_remote_settings_changed(self, event: RemoteSettingsChanged) -> None:
        if SettingCodes.INITIAL_WINDOW_SIZE in event.changed_settings:
            for stream in self.streams.values():
                stream.__window_updated__.set()

    def process_settings_acknowledged(self, event: SettingsAcknowledged) -> None:
        pass

    def process_data_received(self, event: DataReceived) -> None:
        stream = self.streams.get(event.stream_id)
        if stream is not None:
            none_throws(stream.__buffer__).append(event.data)

    def process_window_updated(self, event: WindowUpdated) -> None:
        if event.stream_id == 0:
            for stream in self.streams.values():
                stream.__window_updated__.set()
        else:
            optional_stream = self.streams.get(event.stream_id)
            if optional_stream is not None:
                optional_stream.__window_updated__.set()

    def process_trailers_received(self, event: TrailersReceived) -> None:
        stream = self.streams.get(event.stream_id)
        if stream is not None:
            stream.__headers__.put_nowait(event.headers)

    def process_stream_ended(self, event: StreamEnded) -> None:
        stream = self.streams.get(event.stream_id)
        if stream is not None:
            stream.__ended__()

    def process_stream_reset(self, event: StreamReset) -> None:
        stream = self.streams.get(event.stream_id)
        if stream is not None:
            if event.remote_reset:
                msg = ('Stream reset by remote party, error_code: {}'
                       .format(event.error_code))
            else:
                msg = 'Protocol error'
            stream.__terminated__(msg)
            self.handler.cancel(stream)

    def process_priority_updated(self, event: PriorityUpdated) -> None:
        pass

    def process_connection_terminated(self, event: ConnectionTerminated) -> None:
        self.close()

    def process_ping_received(self, event: PingReceived) -> None:
        pass

    def process_ping_ack_received(self, event: PingAckReceived) -> None:
        pass


class H2Protocol(Protocol):
    connection = None  # type: Optional[Connection]
    processor = None  # type: Optional[EventsProcessor]

    def __init__(self, handler: AbstractHandler, config: H2Configuration,
                 *, loop: AbstractEventLoop) -> None:
        self.handler = handler
        self.config = config
        self.loop = loop

    def connection_made(self, transport: BaseTransport) -> None:
        sock = transport.get_extra_info('socket')
        if sock is not None:
            _set_nodelay(sock)

        h2_conn = H2Connection(config=self.config)
        h2_conn.initiate_connection()

        assert isinstance(transport, WriteTransport)
        self.connection = Connection(h2_conn, transport, loop=self.loop)
        self.connection.flush()

        self.processor = EventsProcessor(self.handler, self.connection)

    def data_received(self, data: bytes) -> None:
        assert self.connection is not None
        assert self.processor is not None
        try:
            events = self.connection.feed(data)
        except ProtocolError:
            self.processor.close()
        else:
            self.connection.flush()
            for event in events:
                self.processor.process(event)
            self.connection.flush()

    def pause_writing(self) -> None:
        none_throws(self.connection).pause_writing()

    def resume_writing(self) -> None:
        none_throws(self.connection).resume_writing()

    def connection_lost(self, exc: Optional[BaseException]) -> None:
        none_throws(self.processor).close()
