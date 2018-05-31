import pytest
import asyncio

from h2.config import H2Configuration
from h2.events import StreamEnded, WindowUpdated
from h2.settings import SettingCodes
from h2.connection import H2Connection

from grpclib.metadata import Request
from grpclib.protocol import _slice, Connection, EventsProcessor

from stubs import TransportStub, DummyHandler


def create_connections(*, connection_window=None, stream_window=None,
                       max_frame_size=None):
    server_conn = H2Connection(H2Configuration(client_side=False,
                                               header_encoding='utf-8'))
    server_conn.initiate_connection()

    if connection_window is not None:
        initial_window_size = server_conn.local_settings.initial_window_size
        assert connection_window > initial_window_size, (
            '{} should be greater than {}'
            .format(connection_window, initial_window_size)
        )
        server_conn.increment_flow_control_window(
            connection_window - initial_window_size
        )

    if stream_window is not None:
        server_conn.update_settings({
            SettingCodes.INITIAL_WINDOW_SIZE: stream_window
        })

    if max_frame_size is not None:
        server_conn.update_settings({
            SettingCodes.MAX_FRAME_SIZE: max_frame_size
        })

    client_conn = H2Connection(H2Configuration(client_side=True,
                                               header_encoding='utf-8'))
    client_conn.initiate_connection()

    client_conn.receive_data(server_conn.data_to_send())
    server_conn.receive_data(client_conn.data_to_send())
    client_conn.receive_data(server_conn.data_to_send())

    return client_conn, server_conn


def test_slice():
    data, tail = _slice([b'a', b'b', b'c', b'd', b'e', b'f'], 5)
    assert data == [b'a', b'b', b'c', b'd', b'e']
    assert tail == [b'f']

    data, tail = _slice([b'a', b'b', b'cdef'], 5)
    assert data == [b'a', b'b', b'cde']
    assert tail == [b'f']

    data, tail = _slice([b'abc', b'def', b'gh'], 5)
    assert data == [b'abc', b'de']
    assert tail == [b'f', b'gh']

    data, tail = _slice([b'abcde', b'fgh'], 5)
    assert data == [b'abcde']
    assert tail == [b'fgh']

    data, tail = _slice([b'abcdefgh', b'ij'], 5)
    assert data == [b'abcde']
    assert tail == [b'fgh', b'ij']

    data, tail = _slice([b'abcdefgh', b'ij'], 100)
    assert data == [b'abcdefgh', b'ij']
    assert tail == []


@pytest.mark.asyncio
async def test_send_data_larger_than_frame_size(loop):
    client_h2c, server_h2c = create_connections()

    transport = TransportStub(server_h2c)
    conn = Connection(client_h2c, transport, loop=loop)
    stream = conn.create_stream()

    request = Request('POST', 'http', '/',
                      content_type='application/grpc+proto',
                      authority='test.com')
    processor = EventsProcessor(DummyHandler(), conn)

    await stream.send_request(request.to_headers(), _processor=processor)
    await stream.send_data(b'0' * (client_h2c.max_outbound_frame_size + 1))


@pytest.mark.asyncio
async def test_recv_data_larger_than_window_size(loop):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    server_conn = Connection(server_h2c, to_client_transport, loop=loop)

    to_server_transport = TransportStub(server_h2c)
    client_conn = Connection(client_h2c, to_server_transport, loop=loop)

    client_processor = EventsProcessor(DummyHandler(), client_conn)
    client_stream = client_conn.create_stream()

    request = Request('POST', 'http', '/',
                      content_type='application/grpc+proto',
                      authority='test.com')
    await client_stream.send_request(request.to_headers(),
                                     _processor=client_processor)

    initial_window = server_h2c.local_settings.initial_window_size
    assert (client_h2c.local_flow_control_window(client_stream.id)
            == initial_window)

    # data should be bigger than window size
    data = b'0' * (initial_window + 1)
    size = len(data)

    # sending less than a full message
    await client_stream.send_data(data[:initial_window - 1])

    # let server process it's events
    server_processor = EventsProcessor(DummyHandler(), server_conn)
    for event in to_server_transport.events():
        server_processor.process(event)

    # checking window size was decreased
    assert client_h2c.local_flow_control_window(client_stream.id) == 1

    # simulate that server is waiting for the size of a message and should
    # acknowledge that size as soon as it will be received
    server_stream, = server_processor.streams.values()
    recv_task = loop.create_task(server_stream.recv_data(size))
    await asyncio.wait([recv_task], timeout=.01, loop=loop)
    assert server_stream.__buffer__._read_size == size
    assert server_stream.__buffer__._size == initial_window - 1

    # check that server acknowledged received partial data
    assert client_h2c.local_flow_control_window(client_stream.id) > 1

    # sending remaining data and recv_task should finish
    await client_stream.send_data(data[initial_window - 1:])
    for event in to_server_transport.events():
        server_processor.process(event)
    await asyncio.wait_for(recv_task, 0.01, loop=loop)
    assert server_stream.__buffer__._size == 0


@pytest.mark.asyncio
async def test_stream_release(loop):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    server_conn = Connection(server_h2c, to_client_transport, loop=loop)

    to_server_transport = TransportStub(server_h2c)
    client_conn = Connection(client_h2c, to_server_transport, loop=loop)

    client_processor = EventsProcessor(DummyHandler(), client_conn)
    client_stream = client_conn.create_stream()

    server_processor = EventsProcessor(DummyHandler(), server_conn)

    request = Request('POST', 'http', '/',
                      content_type='application/grpc+proto',
                      authority='test.com')

    assert not client_processor.streams
    client_release_stream = await client_stream.send_request(
        request.to_headers(), _processor=client_processor,
    )
    assert client_release_stream and client_processor.streams

    # sending data and closing stream on the client-side
    msg = b'message'
    await client_stream.send_data(msg, end_stream=True)
    events1 = to_server_transport.process(server_processor)
    assert any(isinstance(e, StreamEnded) for e in events1), events1

    # intentionally sending some stream-specific frame after stream was
    # half-closed
    client_h2c.increment_flow_control_window(10, stream_id=client_stream.id)
    client_conn.flush()
    events2 = to_server_transport.process(server_processor)
    assert any(isinstance(e, WindowUpdated) for e in events2), events2

    server_stream, = server_processor.streams.values()
    await server_stream.recv_data(len(msg))
    await server_stream.end()

    events3 = to_client_transport.process(client_processor)
    assert any(isinstance(e, StreamEnded) for e in events3), events3

    # simulating request handler exit by releasing server-side stream
    server_processor.handler.release_stream()
    assert not server_processor.streams

    # simulating call exit by releasing client-side stream
    assert client_processor.streams
    client_release_stream()
    assert not client_processor.streams
