import asyncio

from unittest.mock import Mock

import pytest
import async_timeout
import pytest_asyncio

from faker import Faker
from h2.events import StreamReset, StreamEnded
from multidict import MultiDict
from h2.settings import SettingCodes

from grpclib.const import Status, Cardinality
from grpclib.client import Stream
from grpclib.events import _DispatchChannelEvents
from grpclib.metadata import USER_AGENT
from grpclib.exceptions import GRPCError, StreamTerminatedError, ProtocolError
from grpclib.encoding.proto import ProtoCodec

from conn import ClientStream, ClientConn, grpc_encode
from dummy_pb2 import DummyRequest, DummyReply


fake = Faker()


@pytest_asyncio.fixture(name='cs')
async def client_stream_fixture():
    return ClientStream(send_type=DummyRequest, recv_type=DummyReply)


class ClientError(Exception):
    pass


class ErrorDetected(Exception):
    pass


@pytest.mark.asyncio
async def test_unary_unary(cs: ClientStream):
    async with cs.client_stream as stream:
        await stream.send_message(DummyRequest(value='ping'))

        events = cs.client_conn.to_server_transport.events()
        event = events[-1]
        assert isinstance(event, StreamEnded)
        stream_id = event.stream_id

        cs.client_conn.server_h2c.send_headers(
            stream_id,
            [(':status', '200'),
             ('content-type', 'application/grpc+proto')],
        )
        cs.client_conn.server_h2c.send_data(
            stream_id,
            grpc_encode(DummyReply(value='pong'), DummyReply),
        )
        cs.client_conn.server_h2c.send_headers(
            stream_id,
            [('grpc-status', str(Status.OK.value))],
            end_stream=True,
        )
        cs.client_conn.server_flush()

        assert await stream.recv_message() == DummyReply(value='pong')


@pytest.mark.asyncio
async def test_no_request(cs: ClientStream):
    async with cs.client_stream:
        pass


@pytest.mark.asyncio
async def test_no_end():
    cs = ClientStream(send_type=DummyRequest, recv_type=DummyReply,
                      cardinality=Cardinality.STREAM_UNARY)
    with pytest.raises(ProtocolError) as exc:
        async with cs.client_stream as stream:
            await stream.send_request()
            await stream.send_message(DummyRequest(value='ping'))  # no end

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id
            cs.client_conn.server_h2c.send_headers(
                stream_id,
                [(':status', '200'),
                 ('content-type', 'application/grpc+proto')],
            )
            cs.client_conn.server_flush()
            await stream.recv_initial_metadata()

            cs.client_conn.server_h2c.send_data(
                stream_id,
                grpc_encode(DummyReply(value='pong'), DummyReply),
            )
            cs.client_conn.server_flush()
            assert await stream.recv_message() == DummyReply(value='pong')

            await stream.recv_trailing_metadata()
    exc.match('Outgoing stream was not ended')


@pytest.mark.asyncio
async def test_connection_error():
    class BrokenChannel:
        _calls_started = 0

        def __connect__(self):
            raise IOError('Intentionally broken connection')

    stream = Stream(BrokenChannel(), '/foo/bar', MultiDict(),
                    Cardinality.UNARY_UNARY, DummyRequest, DummyReply,
                    codec=ProtoCodec(), status_details_codec=None,
                    dispatch=_DispatchChannelEvents())

    with pytest.raises(IOError) as err:
        async with stream:
            await stream.send_request()
    err.match('Intentionally broken connection')


@pytest.mark.asyncio
async def test_ctx_exit_with_error_and_closed_stream(cs):
    with pytest.raises(ClientError):
        async with cs.client_stream as stream:
            await stream.send_request()
            events = cs.client_conn.to_server_transport.events()
            cs.client_conn.server_h2c.reset_stream(events[-1].stream_id)
            cs.client_conn.server_flush()
            raise ClientError()


@pytest.mark.asyncio
async def test_ctx_exit_with_error_and_closed_connection(cs):
    with pytest.raises(ClientError):
        async with cs.client_stream as stream:
            await stream.send_request()
            cs.client_conn.server_h2c.close_connection()
            cs.client_conn.server_flush()
            raise ClientError()


@pytest.mark.asyncio
async def test_outbound_streams_limit(loop):
    client_conn = ClientConn()
    client_conn.server_h2c.update_settings({
        SettingCodes.MAX_CONCURRENT_STREAMS: 1,
    })
    client_conn.server_flush()

    async def worker1():
        cs = ClientStream(client_conn=client_conn,
                          send_type=DummyRequest, recv_type=DummyReply)
        async with cs.client_stream as stream:
            await stream.send_message(DummyRequest(value='ping'), end=True)
            assert await stream.recv_message() == DummyReply(value='pong')

    async def worker2():
        cs = ClientStream(client_conn=client_conn,
                          send_type=DummyRequest, recv_type=DummyReply)
        async with cs.client_stream as stream:
            await stream.send_message(DummyRequest(value='ping'), end=True)
            assert await stream.recv_message() == DummyReply(value='pong')

    def send_response(stream_id):
        client_conn.server_h2c.send_headers(
            stream_id,
            [
                (':status', '200'),
                ('content-type', 'application/grpc+proto'),
            ],
        )
        client_conn.server_h2c.send_data(
            stream_id,
            grpc_encode(DummyReply(value='pong'), DummyReply),
        )
        client_conn.server_h2c.send_headers(
            stream_id,
            [
                ('grpc-status', str(Status.OK.value)),
            ],
            end_stream=True,
        )
        client_conn.server_flush()

    w1 = loop.create_task(worker1())
    w2 = loop.create_task(worker2())

    done, pending = await asyncio.wait([w1, w2], timeout=0.001)
    assert not done and pending == {w1, w2}

    send_response(1)
    await asyncio.wait_for(w1, 0.1)

    send_response(3)
    await asyncio.wait_for(w2, 0.1)


@pytest.mark.asyncio
async def test_deadline_during_send_request():
    cs = ClientStream(timeout=0.01, connect_time=1,
                      send_type=DummyRequest, recv_type=DummyReply)
    with pytest.raises(ErrorDetected):
        async with async_timeout.timeout(5) as safety_timeout:
            async with cs.client_stream as stream:
                try:
                    await stream.send_request()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise ErrorDetected()


@pytest.mark.asyncio
async def test_deadline_during_send_message():
    cs = ClientStream(timeout=0.01,
                      send_type=DummyRequest, recv_type=DummyReply)
    with pytest.raises(ErrorDetected):
        async with async_timeout.timeout(5) as safety_timeout:
            async with cs.client_stream as stream:
                await stream.send_request()

                cs.client_conn.client_proto.connection.write_ready.clear()
                try:
                    await stream.send_message(DummyRequest(value='ping'),
                                              end=True)
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise ErrorDetected()


@pytest.mark.asyncio
async def test_deadline_during_recv_initial_metadata():
    cs = ClientStream(timeout=0.01,
                      send_type=DummyRequest, recv_type=DummyReply)
    with pytest.raises(ErrorDetected):
        async with async_timeout.timeout(5) as safety_timeout:
            async with cs.client_stream as stream:
                await stream.send_message(DummyRequest(value='ping'),
                                          end=True)

                try:
                    await stream.recv_initial_metadata()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise ErrorDetected()


@pytest.mark.asyncio
async def test_deadline_during_recv_message():
    cs = ClientStream(timeout=0.01,
                      send_type=DummyRequest, recv_type=DummyReply)
    with pytest.raises(ErrorDetected):
        async with async_timeout.timeout(5) as safety_timeout:
            async with cs.client_stream as stream:
                await stream.send_message(DummyRequest(value='ping'), end=True)

                events = cs.client_conn.to_server_transport.events()
                stream_id = events[-1].stream_id
                cs.client_conn.server_h2c.send_headers(
                    stream_id,
                    [(':status', '200'),
                     ('content-type', 'application/grpc+proto')],
                )
                cs.client_conn.server_flush()
                await stream.recv_initial_metadata()

                try:
                    await stream.recv_message()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise ErrorDetected()


@pytest.mark.asyncio
async def test_deadline_during_recv_trailing_metadata():
    cs = ClientStream(timeout=0.01,
                      send_type=DummyRequest, recv_type=DummyReply)
    with pytest.raises(ErrorDetected):
        async with async_timeout.timeout(5) as safety_timeout:
            async with cs.client_stream as stream:
                await stream.send_message(DummyRequest(value='ping'), end=True)

                events = cs.client_conn.to_server_transport.events()
                stream_id = events[-1].stream_id

                cs.client_conn.server_h2c.send_headers(
                    stream_id,
                    [(':status', '200'),
                     ('content-type', 'application/grpc+proto')],
                )
                cs.client_conn.server_flush()
                await stream.recv_initial_metadata()

                cs.client_conn.server_h2c.send_data(
                    stream_id,
                    grpc_encode(DummyReply(value='pong'), DummyReply),
                )
                cs.client_conn.server_flush()
                await stream.recv_message()

                try:
                    await stream.recv_trailing_metadata()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise ErrorDetected()


@pytest.mark.asyncio
async def test_deadline_during_cancel():
    cs = ClientStream(timeout=0.01,
                      send_type=DummyRequest, recv_type=DummyReply)
    with pytest.raises(ErrorDetected):
        async with async_timeout.timeout(5) as safety_timeout:
            async with cs.client_stream as stream:
                await stream.send_request()

                cs.client_conn.client_proto.connection.write_ready.clear()
                try:
                    await stream.cancel()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise ErrorDetected()


@pytest.mark.asyncio
async def test_stream_reset_during_send_message(loop, cs: ClientStream):
    with pytest.raises(ErrorDetected):
        async with cs.client_stream as stream:
            await stream.send_request()

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id
            cs.client_conn.client_proto.connection.write_ready.clear()
            task = loop.create_task(
                stream.send_message(DummyRequest(value='ping'), end=True)
            )
            cs.client_conn.server_h2c.reset_stream(stream_id)
            cs.client_conn.server_flush()

            try:
                await asyncio.wait_for(task, timeout=1)
            except StreamTerminatedError:
                raise ErrorDetected()


@pytest.mark.asyncio
async def test_connection_close_during_send_message(loop, cs: ClientStream):
    with pytest.raises(ErrorDetected):
        async with cs.client_stream as stream:
            await stream.send_request()

            cs.client_conn.client_proto.connection.write_ready.clear()
            task = loop.create_task(
                stream.send_message(DummyRequest(value='ping'), end=True)
            )
            cs.client_conn.server_h2c.close_connection()
            cs.client_conn.server_flush()

            try:
                await asyncio.wait_for(task, timeout=1)
            except StreamTerminatedError:
                raise ErrorDetected()


@pytest.mark.asyncio
async def test_unimplemented_error(cs: ClientStream):
    with pytest.raises(ErrorDetected):
        async with cs.client_stream as stream:
            await stream.send_request()

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            cs.client_conn.server_h2c.send_headers(stream_id, [
                (':status', '200'),
                ('content-type', 'application/grpc+proto'),
                ('grpc-status', str(Status.UNIMPLEMENTED.value)),
            ], end_stream=True)
            cs.client_conn.server_flush()

            try:
                await stream.recv_initial_metadata()
            except GRPCError as exc:
                assert exc and exc.status == Status.UNIMPLEMENTED
                raise ErrorDetected()


@pytest.mark.asyncio
async def test_unimplemented_error_with_stream_reset(cs: ClientStream):
    with pytest.raises(GRPCError) as err:
        async with cs.client_stream as stream:
            await stream.send_request()

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            cs.client_conn.server_h2c.send_headers(stream_id, [
                (':status', '200'),
                ('content-type', 'application/grpc+proto'),
                ('grpc-status', str(Status.UNIMPLEMENTED.value)),
            ], end_stream=True)
            cs.client_conn.server_h2c.reset_stream(stream_id)
            cs.client_conn.server_flush()

    assert err.value.status == Status.UNIMPLEMENTED


@pytest.mark.asyncio
@pytest.mark.parametrize('status, grpc_status', [
    ('401', Status.UNAUTHENTICATED),
    ('404', Status.UNIMPLEMENTED),
    ('429', Status.UNAVAILABLE),
    ('508', Status.UNKNOWN),
])
async def test_non_ok_status(cs: ClientStream, status, grpc_status):
    with pytest.raises(GRPCError) as err:
        async with cs.client_stream as stream:
            await stream.send_request()

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            cs.client_conn.server_h2c.send_headers(stream_id, [
                (':status', status),
            ], end_stream=True)
            cs.client_conn.server_h2c.reset_stream(stream_id)
            cs.client_conn.server_flush()

    assert err.value.status == grpc_status
    assert err.value.message == 'Received :status = {!r}'.format(status)


@pytest.mark.asyncio
async def test_reset_after_headers(cs: ClientStream):
    with pytest.raises(StreamTerminatedError):
        async with cs.client_stream as stream:
            await stream.send_request()

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            cs.client_conn.server_h2c.send_headers(stream_id, [
                (':status', '200'),
            ])
            cs.client_conn.server_h2c.reset_stream(stream_id)
            cs.client_conn.server_flush()


@pytest.mark.asyncio
async def test_missing_grpc_status(cs: ClientStream):
    with pytest.raises(ErrorDetected):
        async with cs.client_stream as stream:
            await stream.send_request()
            await stream.send_message(DummyRequest(value='ping'), end=True)

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            cs.client_conn.server_h2c.send_headers(stream_id, [
                (':status', '200'),
                ('content-type', 'application/grpc+proto'),
            ])
            cs.client_conn.server_h2c.send_data(
                stream_id,
                grpc_encode(DummyReply(value='pong'), DummyReply),
            )
            cs.client_conn.server_h2c.send_headers(stream_id, [
                ('foo', 'bar'),
            ], end_stream=True)
            cs.client_conn.server_flush()

            await stream.recv_initial_metadata()
            await stream.recv_message()
            try:
                await stream.recv_trailing_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == Status.UNKNOWN
                assert exc.message == 'Missing grpc-status header'
                raise ErrorDetected()


@pytest.mark.asyncio
@pytest.mark.parametrize('grpc_status', ['invalid_number', '-42'])
async def test_invalid_grpc_status_in_headers(cs: ClientStream, grpc_status):
    with pytest.raises(ErrorDetected):
        async with cs.client_stream as stream:
            await stream.send_request()
            await stream.send_message(DummyRequest(value='ping'), end=True)

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            cs.client_conn.server_h2c.send_headers(stream_id, [
                (':status', '200'),
                ('content-type', 'application/grpc+proto'),
                ('grpc-status', grpc_status),
            ], end_stream=True)
            cs.client_conn.server_flush()

            try:
                await stream.recv_initial_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == Status.UNKNOWN
                assert exc.message == ('Invalid grpc-status: {!r}'
                                       .format(grpc_status))
                raise ErrorDetected()


@pytest.mark.asyncio
@pytest.mark.parametrize('grpc_status', ['invalid_number', '-42'])
async def test_invalid_grpc_status_in_trailers(cs: ClientStream, grpc_status):
    with pytest.raises(ErrorDetected):
        async with cs.client_stream as stream:
            await stream.send_request()
            await stream.send_message(DummyRequest(value='ping'), end=True)

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            cs.client_conn.server_h2c.send_headers(stream_id, [
                (':status', '200'),
                ('content-type', 'application/grpc+proto'),
            ])
            cs.client_conn.server_h2c.send_data(
                stream_id,
                grpc_encode(DummyReply(value='pong'), DummyReply),
            )
            cs.client_conn.server_h2c.send_headers(stream_id, [
                ('grpc-status', grpc_status),
            ], end_stream=True)
            cs.client_conn.server_flush()

            await stream.recv_initial_metadata()
            await stream.recv_message()
            try:
                await stream.recv_trailing_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == Status.UNKNOWN
                assert exc.message == ('Invalid grpc-status: {!r}'
                                       .format(grpc_status))
                raise ErrorDetected()


@pytest.mark.asyncio
@pytest.mark.parametrize('grpc_message', [None, fake.pystr()])
async def test_non_ok_grpc_status_in_headers(cs: ClientStream, grpc_message):
    with pytest.raises(ErrorDetected):
        async with cs.client_stream as stream:
            await stream.send_request()
            await stream.send_message(DummyRequest(value='ping'), end=True)

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            headers = [
                (':status', '200'),
                ('content-type', 'application/grpc+proto'),
                ('grpc-status', str(Status.DATA_LOSS.value)),
            ]
            if grpc_message is not None:
                headers.append(('grpc-message', grpc_message))
            cs.client_conn.server_h2c.send_headers(stream_id, headers,
                                                   end_stream=True)
            cs.client_conn.server_flush()

            try:
                await stream.recv_initial_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == Status.DATA_LOSS
                assert exc.message == grpc_message
                raise ErrorDetected()


@pytest.mark.asyncio
@pytest.mark.parametrize('grpc_message', [None, fake.pystr()])
async def test_non_ok_grpc_status_in_trailers(cs: ClientStream, grpc_message):
    with pytest.raises(ErrorDetected):
        async with cs.client_stream as stream:
            await stream.send_request()
            await stream.send_message(DummyRequest(value='ping'), end=True)

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            cs.client_conn.server_h2c.send_headers(stream_id, [
                (':status', '200'),
                ('content-type', 'application/grpc+proto'),
            ])
            cs.client_conn.server_h2c.send_data(
                stream_id,
                grpc_encode(DummyReply(value='pong'), DummyReply),
            )
            headers = [
                ('grpc-status', str(Status.DATA_LOSS.value)),
            ]
            if grpc_message is not None:
                headers.append(('grpc-message', grpc_message))
            cs.client_conn.server_h2c.send_headers(stream_id, headers,
                                                   end_stream=True)
            cs.client_conn.server_flush()

            await stream.recv_initial_metadata()
            await stream.recv_message()
            try:
                await stream.recv_trailing_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == Status.DATA_LOSS
                assert exc.message == grpc_message
                raise ErrorDetected()


@pytest.mark.asyncio
async def test_missing_content_type(cs: ClientStream):
    with pytest.raises(ErrorDetected):
        async with cs.client_stream as stream:
            await stream.send_request()
            await stream.send_message(DummyRequest(value='ping'), end=True)

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            cs.client_conn.server_h2c.send_headers(stream_id, [
                (':status', '200'),
                ('grpc-status', str(Status.OK.value)),
            ])
            cs.client_conn.server_flush()

            try:
                await stream.recv_initial_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == Status.UNKNOWN
                assert exc.message == "Missing content-type header"
                raise ErrorDetected()


@pytest.mark.asyncio
async def test_invalid_content_type(cs: ClientStream):
    with pytest.raises(ErrorDetected):
        async with cs.client_stream as stream:
            await stream.send_request()
            await stream.send_message(DummyRequest(value='ping'), end=True)

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            cs.client_conn.server_h2c.send_headers(stream_id, [
                (':status', '200'),
                ('grpc-status', str(Status.OK.value)),
                ('content-type', 'text/invalid'),
            ])
            cs.client_conn.server_flush()

            try:
                await stream.recv_initial_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == Status.UNKNOWN
                assert exc.message == "Invalid content-type: 'text/invalid'"
                raise ErrorDetected()


@pytest.mark.asyncio
async def test_request_headers(cs: ClientStream):
    async with cs.client_stream as stream:
        await stream.send_request()
        events = cs.client_conn.to_server_transport.events()
        request_received = events[-1]
        assert request_received.headers == [
            (':method', 'POST'),
            (':scheme', 'http'),
            (':path', '/foo/bar'),
            (':authority', 'test.com'),
            ('te', 'trailers'),
            ('content-type', 'application/grpc'),
            ('user-agent', USER_AGENT),
        ]
        await stream.cancel()


@pytest.mark.asyncio
async def test_request_headers_with_deadline():
    deadline = Mock()
    deadline.time_remaining.return_value = 0.1
    cs = ClientStream(deadline=deadline)
    async with cs.client_stream as stream:
        await stream.send_request()
        events = cs.client_conn.to_server_transport.events()
        request_received = events[-1]
        assert request_received.headers == [
            (':method', 'POST'),
            (':scheme', 'http'),
            (':path', '/foo/bar'),
            (':authority', 'test.com'),
            ('grpc-timeout', '100m'),
            ('te', 'trailers'),
            ('content-type', 'application/grpc'),
            ('user-agent', USER_AGENT),
        ]
        await stream.cancel()


@pytest.mark.asyncio
async def test_no_messages_for_unary(loop, cs: ClientStream):
    with pytest.raises(ProtocolError, match='Unary request requires'):
        async with cs.client_stream as stream:
            await stream.send_request()
            cs.client_conn.to_server_transport.events()
            await stream.end()
    reset_event, = cs.client_conn.to_server_transport.events()
    assert isinstance(reset_event, StreamReset)


@pytest.mark.asyncio
async def test_empty_request():
    cs = ClientStream(cardinality=Cardinality.STREAM_UNARY,
                      send_type=DummyRequest, recv_type=DummyReply)
    async with cs.client_stream as stream:
        await stream.send_request(end=True)
        events = cs.client_conn.to_server_transport.events()
        stream_ended = events[-1]
        assert isinstance(stream_ended, StreamEnded)
        stream_id = stream_ended.stream_id
        cs.client_conn.server_h2c.send_headers(stream_id, [
            (':status', '200'),
            ('content-type', 'application/grpc+proto'),
        ])
        cs.client_conn.server_h2c.send_data(
            stream_id,
            grpc_encode(DummyReply(value='pong'), DummyReply),
        )
        cs.client_conn.server_h2c.send_headers(stream_id, [
            ('grpc-status', str(Status.OK.value)),
        ], end_stream=True)
        cs.client_conn.server_flush()

        reply = await stream.recv_message()
        assert reply == DummyReply(value='pong')


@pytest.mark.asyncio
async def test_empty_response():
    cs = ClientStream(cardinality=Cardinality.UNARY_STREAM,
                      send_type=DummyRequest, recv_type=DummyReply)
    async with cs.client_stream as stream:
        await stream.send_message(DummyRequest(value='ping'), end=True)
        events = cs.client_conn.to_server_transport.events()
        stream_id = events[-1].stream_id
        cs.client_conn.server_h2c.send_headers(stream_id, [
            (':status', '200'),
            ('content-type', 'application/grpc+proto'),
        ])
        cs.client_conn.server_h2c.send_headers(stream_id, [
            ('grpc-status', str(Status.OK.value)),
        ], end_stream=True)
        cs.client_conn.server_flush()
        reply = await stream.recv_message()
        assert reply is None


@pytest.mark.asyncio
async def test_empty_trailers_only_response():
    cs = ClientStream(cardinality=Cardinality.UNARY_STREAM,
                      send_type=DummyRequest, recv_type=DummyReply)
    async with cs.client_stream as stream:
        await stream.send_message(DummyRequest(value='ping'), end=True)
        events = cs.client_conn.to_server_transport.events()
        stream_id = events[-1].stream_id
        cs.client_conn.server_h2c.send_headers(stream_id, [
            (':status', '200'),
            ('content-type', 'application/grpc+proto'),
            ('grpc-status', str(Status.OK.value)),
        ], end_stream=True)
        cs.client_conn.server_flush()
        reply = await stream.recv_message()
        assert reply is None
        await stream.recv_trailing_metadata()  # should be noop
