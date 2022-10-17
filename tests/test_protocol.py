from unittest.mock import Mock

import pytest
import asyncio

from h2.config import H2Configuration
from h2.events import StreamEnded, WindowUpdated, PingAckReceived
from h2.settings import SettingCodes
from h2.connection import H2Connection
from h2.exceptions import StreamClosedError

from grpclib.const import Status
from grpclib.utils import Wrapper
from grpclib.config import Configuration
from grpclib.protocol import Connection, EventsProcessor, Peer, H2Protocol
from grpclib.exceptions import StreamTerminatedError

from stubs import TransportStub, DummyHandler


def create_connections(*, connection_window=None, stream_window=None,
                       max_frame_size=None):
    server_conn = H2Connection(H2Configuration(client_side=False,
                                               header_encoding='ascii'))
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
                                               header_encoding='ascii'))
    client_conn.initiate_connection()

    client_conn.receive_data(server_conn.data_to_send())
    server_conn.receive_data(client_conn.data_to_send())
    client_conn.receive_data(server_conn.data_to_send())

    return client_conn, server_conn


def create_headers(*, path='/any/path'):
    return [
        (':method', 'POST'),
        (':scheme', 'http'),
        (':path', path),
        (':authority', 'test.com'),
        ('te', 'trailers'),
        ('content-type', 'application/grpc+proto'),
    ]


@pytest.mark.asyncio
async def test_send_data_larger_than_frame_size(config):
    client_h2c, server_h2c = create_connections()

    transport = TransportStub(server_h2c)
    conn = Connection(client_h2c, transport, config=config)
    stream = conn.create_stream()

    processor = EventsProcessor(DummyHandler(), conn)

    await stream.send_request(create_headers(), _processor=processor)
    await stream.send_data(b'0' * (client_h2c.max_outbound_frame_size + 1))


@pytest.mark.asyncio
async def test_recv_data_larger_than_window_size(loop, config):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    server_conn = Connection(server_h2c, to_client_transport, config=config)

    to_server_transport = TransportStub(server_h2c)
    client_conn = Connection(client_h2c, to_server_transport, config=config)

    client_proc = EventsProcessor(DummyHandler(), client_conn)
    client_stream = client_conn.create_stream()

    await client_stream.send_request(create_headers(), _processor=client_proc)

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
    to_server_transport.process(server_processor)

    # checking window size was decreased
    assert client_h2c.local_flow_control_window(client_stream.id) == 1

    # simulate that server is waiting for the size of a message and should
    # acknowledge that size as soon as it will be received
    server_stream, = server_processor.streams.values()
    recv_task = loop.create_task(server_stream.recv_data(size))
    await asyncio.wait([recv_task], timeout=.01)
    assert server_stream.buffer._acked_size == initial_window - 1

    # check that server acknowledged received partial data
    assert client_h2c.local_flow_control_window(client_stream.id) > 1

    # sending remaining data and recv_task should finish
    await client_stream.send_data(data[initial_window - 1:])
    to_server_transport.process(server_processor)
    await asyncio.wait_for(recv_task, 0.01)
    assert server_stream.buffer._acked_size == 0


@pytest.mark.asyncio
async def test_stream_release(config):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    server_conn = Connection(server_h2c, to_client_transport, config=config)

    to_server_transport = TransportStub(server_h2c)
    client_conn = Connection(client_h2c, to_server_transport, config=config)

    client_processor = EventsProcessor(DummyHandler(), client_conn)
    client_stream = client_conn.create_stream()

    server_processor = EventsProcessor(DummyHandler(), server_conn)

    assert not client_processor.streams
    client_release_stream = await client_stream.send_request(
        create_headers(), _processor=client_processor,
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
    await server_stream.send_headers([(':status', '200')], end_stream=True)

    events3 = to_client_transport.process(client_processor)
    assert any(isinstance(e, StreamEnded) for e in events3), events3

    # simulating request handler exit by releasing server-side stream
    server_processor.handler.release_stream()
    assert not server_processor.streams

    # simulating call exit by releasing client-side stream
    assert client_processor.streams
    client_release_stream()
    assert not client_processor.streams


@pytest.mark.asyncio
async def test_initial_window_size_update(loop, config):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    server_conn = Connection(server_h2c, to_client_transport, config=config)

    to_server_transport = TransportStub(server_h2c)
    client_conn = Connection(client_h2c, to_server_transport, config=config)

    client_proc = EventsProcessor(DummyHandler(), client_conn)
    client_stream = client_conn.create_stream()

    await client_stream.send_request(create_headers(), _processor=client_proc)

    # data should be bigger than window size
    initial_window = server_h2c.local_settings.initial_window_size
    data = b'0' * (initial_window + 1)

    assert (client_h2c.local_flow_control_window(client_stream.id)
            == initial_window)

    # send_data should wait until settings/window updated
    send_task = loop.create_task(client_stream.send_data(data))
    await asyncio.wait([send_task], timeout=0.01)

    assert client_h2c.local_flow_control_window(client_stream.id) == 0

    # updating settings and window, this should increase stream window size
    server_h2c.update_settings({
        SettingCodes.INITIAL_WINDOW_SIZE: initial_window + 1
    })
    server_h2c.increment_flow_control_window(1, stream_id=None)
    server_conn.flush()
    to_client_transport.process(client_proc)

    assert client_h2c.local_flow_control_window(client_stream.id) == 1
    await asyncio.wait([send_task], timeout=0.01)

    assert send_task.result() is None


@pytest.mark.asyncio
async def test_send_headers_into_closed_stream(config):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    server_conn = Connection(server_h2c, to_client_transport, config=config)

    to_server_transport = TransportStub(server_h2c)
    client_conn = Connection(client_h2c, to_server_transport, config=config)

    client_proc = EventsProcessor(DummyHandler(), client_conn)
    client_stream = client_conn.create_stream()

    server_processor = EventsProcessor(DummyHandler(), server_conn)

    await client_stream.send_request(create_headers(), _processor=client_proc)

    to_server_transport.process(server_processor)

    server_stream, = server_processor.streams.values()
    server_stream._h2_connection.streams.pop(server_stream.id)
    with pytest.raises(StreamClosedError):
        await server_stream.send_headers([(':status', '200')])


@pytest.mark.asyncio
async def test_ping(config):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    server_conn = Connection(server_h2c, to_client_transport, config=config)

    to_server_transport = TransportStub(server_h2c)
    client_conn = Connection(client_h2c, to_server_transport, config=config)

    client_processor = EventsProcessor(DummyHandler(), client_conn)
    server_processor = EventsProcessor(DummyHandler(), server_conn)

    client_h2c.ping(b'12345678')
    client_conn.flush()

    to_server_transport.process(server_processor)
    server_conn.flush()

    ping_ack, = to_client_transport.process(client_processor)
    assert isinstance(ping_ack, PingAckReceived)
    assert ping_ack.ping_data == b'12345678'


@pytest.mark.asyncio
async def test_unread_data_ack(config):
    client_h2c, server_h2c = create_connections()
    initial_window = client_h2c.outbound_flow_control_window
    # should be large enough to trigger WINDOW_UPDATE frame
    data_size = initial_window - 1

    to_client_transport = TransportStub(client_h2c)
    server_handler = DummyHandler()
    server_conn = Connection(server_h2c, to_client_transport, config=config)
    server_proc = EventsProcessor(server_handler, server_conn)

    to_server_transport = TransportStub(server_h2c)
    client_conn = Connection(client_h2c, to_server_transport, config=config)
    client_proc = EventsProcessor(DummyHandler(), client_conn)
    client_stream = client_conn.create_stream()

    await client_stream.send_request(create_headers(), _processor=client_proc)
    await client_stream.send_data(b'x' * data_size)
    assert client_h2c.outbound_flow_control_window == initial_window - data_size
    to_server_transport.process(server_proc)

    # server_handler.stream.recv_data(data_size) intentionally not called
    await server_handler.stream.send_headers([  # trailers-only error
        (':status', '200'),
        ('content-type', 'application/grpc+proto'),
        ('grpc-status', str(Status.UNKNOWN.value)),
    ], end_stream=True)
    to_client_transport.process(client_proc)

    assert client_h2c.outbound_flow_control_window == initial_window - data_size
    server_handler.release_stream()  # should ack received data
    assert client_h2c.outbound_flow_control_window == initial_window


@pytest.mark.asyncio
async def test_released_stream_data_ack(config):
    client_h2c, server_h2c = create_connections()
    initial_window = client_h2c.outbound_flow_control_window
    # should be large enough to trigger WINDOW_UPDATE frame
    data_size = initial_window - 1

    to_client_transport = TransportStub(client_h2c)
    server_handler = DummyHandler()
    server_conn = Connection(server_h2c, to_client_transport, config=config)
    server_proc = EventsProcessor(server_handler, server_conn)

    to_server_transport = TransportStub(server_h2c)
    client_conn = Connection(client_h2c, to_server_transport, config=config)
    client_proc = EventsProcessor(DummyHandler(), client_conn)
    client_stream = client_conn.create_stream()

    await client_stream.send_request(create_headers(), _processor=client_proc)
    to_server_transport.process(server_proc)

    # server_handler.stream.recv_data(data_size) intentionally not called
    await server_handler.stream.send_headers([  # trailers-only error
        (':status', '200'),
        ('content-type', 'application/grpc+proto'),
        ('grpc-status', str(Status.UNKNOWN.value)),
    ], end_stream=True)
    to_client_transport.process(client_proc)
    server_handler.release_stream()

    assert client_h2c.outbound_flow_control_window == initial_window
    await client_stream.send_data(b'x' * data_size)
    assert client_h2c.outbound_flow_control_window == 1
    to_server_transport.process(server_proc)
    # client-side flow control window will increase to initial value eventually
    assert client_h2c.outbound_flow_control_window > 1


@pytest.mark.asyncio
async def test_negative_window_size(loop, config):
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    server_conn = Connection(server_h2c, to_client_transport, config=config)

    to_server_transport = TransportStub(server_h2c)
    client_conn = Connection(client_h2c, to_server_transport, config=config)

    client_proc = EventsProcessor(DummyHandler(), client_conn)
    client_stream = client_conn.create_stream()

    await client_stream.send_request(create_headers(), _processor=client_proc)

    # data should be bigger than window size
    initial_window = server_h2c.local_settings.initial_window_size
    data = b'0' * (initial_window + 1)

    assert (client_h2c.local_flow_control_window(client_stream.id)
            == initial_window)

    # send_data should wait until settings/window updated
    send_task = loop.create_task(client_stream.send_data(data))
    await asyncio.wait([send_task], timeout=0.01)

    assert client_h2c.local_flow_control_window(client_stream.id) == 0

    # updating settings, this should decrease connection window size
    server_h2c.update_settings({
        SettingCodes.INITIAL_WINDOW_SIZE: initial_window - 1
    })
    server_conn.flush()
    to_client_transport.process(client_proc)

    # window is negative and client should wait
    assert client_h2c.local_flow_control_window(client_stream.id) == -1
    await asyncio.wait([send_task], timeout=0.01)
    assert not send_task.done()

    # now `send_data` should succeed
    server_h2c.increment_flow_control_window(2, stream_id=client_stream.id)
    # INITIAL_WINDOW_SIZE not changes connection's window size, so it should be
    # incremented only by 1
    server_h2c.increment_flow_control_window(1, stream_id=None)
    server_conn.flush()
    to_client_transport.process(client_proc)
    assert client_h2c.local_flow_control_window(client_stream.id) == 1
    await asyncio.wait([send_task], timeout=0.01)
    assert send_task.result() is None


@pytest.mark.asyncio
async def test_receive_goaway(config):
    wrapper = Wrapper()
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    server_conn = Connection(server_h2c, to_client_transport, config=config)

    to_server_transport = TransportStub(server_h2c)
    client_conn = Connection(client_h2c, to_server_transport, config=config)
    client_proc = EventsProcessor(DummyHandler(), client_conn)
    client_stream = client_conn.create_stream(wrapper=wrapper)

    await client_stream.send_request(create_headers(), _processor=client_proc)

    server_h2c.close_connection()
    server_conn.flush()
    to_client_transport.process(client_proc)

    with pytest.raises(StreamTerminatedError, match='Received GOAWAY frame'):
        with wrapper:
            pass


@pytest.mark.asyncio
async def test_release_stream_after_close(config):
    client_h2c, server_h2c = create_connections()

    to_server_transport = TransportStub(server_h2c)
    client_conn = Connection(client_h2c, to_server_transport, config=config)
    client_proc = EventsProcessor(DummyHandler(), client_conn)

    client_stream = client_conn.create_stream()
    release_stream = await client_stream.send_request(create_headers(),
                                                      _processor=client_proc)

    # to trigger connection.ack
    client_stream.buffer.add(b'test', 4)

    # to trigger data send
    client_h2c.ping(b'00000000')

    client_proc.close('test')
    release_stream()


def test_peer_addr():
    transport = Mock()
    transport.get_extra_info.return_value = ('123.45.67.89', 42)

    peer = Peer(transport)
    assert peer.addr() == ('123.45.67.89', 42)
    transport.get_extra_info.assert_called_once_with('peername')


@pytest.mark.parametrize('cert', [None, object()])
def test_peer_cert(cert):
    ssl_object = Mock()
    ssl_object.getpeercert.return_value = cert

    transport = Mock()
    transport.get_extra_info.return_value = ssl_object

    peer = Peer(transport)
    assert peer.cert() is cert
    transport.get_extra_info.assert_called_once_with('ssl_object')
    ssl_object.getpeercert.assert_called_once_with()


@pytest.mark.parametrize('config', [
    Configuration(http2_connection_window_size=2**16 - 1),
    Configuration(http2_connection_window_size=2**31 - 1),
    Configuration(http2_stream_window_size=2**16 - 1),
    Configuration(http2_stream_window_size=2**31 - 1),
])
def test_max_window_size(config):
    server_h2c = H2Connection(H2Configuration(client_side=False,
                                              header_encoding='ascii'))
    proto = H2Protocol(Mock(), config.__for_test__(),
                       H2Configuration(client_side=True))
    proto.connection_made(TransportStub(server_h2c))
    assert server_h2c.outbound_flow_control_window \
        == config.http2_connection_window_size
    assert server_h2c.remote_settings.initial_window_size \
        == config.http2_stream_window_size


@pytest.mark.asyncio
async def test_goaway_twice(config):
    """
    We should be able to receive frames after connection close with GOAWAY frame
    """
    client_h2c, server_h2c = create_connections()

    to_client_transport = TransportStub(client_h2c)
    server_conn = Connection(server_h2c, to_client_transport, config=config)

    to_server_transport = TransportStub(server_h2c)
    client_conn = Connection(client_h2c, to_server_transport, config=config)

    server_processor = EventsProcessor(DummyHandler(), server_conn)

    client_h2c.close_connection()
    client_h2c.close_connection()
    client_conn.flush()
    to_server_transport.process(server_processor)
