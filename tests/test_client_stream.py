import asyncio

import pytest
import async_timeout

from faker import Faker
from h2.settings import SettingCodes

from grpclib.const import Status
from grpclib.client import Stream
from grpclib.metadata import Request
from grpclib.exceptions import GRPCError, StreamTerminatedError
from grpclib.encoding.proto import ProtoCodec

from conn import ClientStream, ClientConn, grpc_encode
from dummy_pb2 import DummyRequest, DummyReply


fake = Faker()


@pytest.fixture(name='cs')
def client_stream_fixture(loop):
    return ClientStream(loop=loop, send_type=DummyRequest, recv_type=DummyReply)


class ClientError(Exception):
    pass


class ErrorDetected(Exception):
    pass


@pytest.mark.asyncio
async def test_unary_unary(cs: ClientStream):
    async with cs.client_stream as stream:
        await stream.send_message(DummyRequest(value='ping'), end=True)

        events = cs.client_conn.to_server_transport.events()
        stream_id = events[-1].stream_id

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
async def test_connection_error():
    request = Request('POST', 'http', '/foo/bar',
                      content_type='application/grpc+proto',
                      authority='test.com')

    class BrokenChannel:
        def __connect__(self):
            raise IOError('Intentionally broken connection')

    stream = Stream(BrokenChannel(), request, ProtoCodec(),
                    DummyRequest, DummyReply)

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
    client_conn = ClientConn(loop=loop)
    client_conn.server_h2c.update_settings({
        SettingCodes.MAX_CONCURRENT_STREAMS: 1,
    })
    client_conn.server_flush()

    async def worker1():
        cs = ClientStream(loop=loop, client_conn=client_conn,
                          send_type=DummyRequest, recv_type=DummyReply)
        async with cs.client_stream as stream:
            await stream.send_message(DummyRequest(value='ping'), end=True)
            assert await stream.recv_message() == DummyReply(value='pong')

    async def worker2():
        cs = ClientStream(loop=loop, client_conn=client_conn,
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

    done, pending = await asyncio.wait([w1, w2], loop=loop, timeout=0.001)
    assert not done and pending == {w1, w2}

    send_response(1)
    await asyncio.wait_for(w1, 0.1, loop=loop)

    send_response(3)
    await asyncio.wait_for(w2, 0.1, loop=loop)


@pytest.mark.asyncio
async def test_deadline_during_send_request(loop):
    cs = ClientStream(loop=loop, timeout=0.01, connect_time=1,
                      send_type=DummyRequest, recv_type=DummyReply)
    with pytest.raises(ErrorDetected):
        with async_timeout.timeout(5) as safety_timeout:
            async with cs.client_stream as stream:
                try:
                    await stream.send_request()
                except asyncio.TimeoutError:
                    if safety_timeout.expired:
                        raise
                    else:
                        raise ErrorDetected()


@pytest.mark.asyncio
async def test_deadline_during_send_message(loop):
    cs = ClientStream(loop=loop, timeout=0.01,
                      send_type=DummyRequest, recv_type=DummyReply)
    with pytest.raises(ErrorDetected):
        with async_timeout.timeout(5) as safety_timeout:
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
async def test_deadline_during_recv_initial_metadata(loop):
    cs = ClientStream(loop=loop, timeout=0.01,
                      send_type=DummyRequest, recv_type=DummyReply)
    with pytest.raises(ErrorDetected):
        with async_timeout.timeout(5) as safety_timeout:
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
async def test_deadline_during_recv_message(loop):
    cs = ClientStream(loop=loop, timeout=0.01,
                      send_type=DummyRequest, recv_type=DummyReply)
    with pytest.raises(ErrorDetected):
        with async_timeout.timeout(5) as safety_timeout:
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
async def test_deadline_during_recv_trailing_metadata(loop):
    cs = ClientStream(loop=loop, timeout=0.01,
                      send_type=DummyRequest, recv_type=DummyReply)
    with pytest.raises(ErrorDetected):
        with async_timeout.timeout(5) as safety_timeout:
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
async def test_deadline_during_cancel(loop):
    cs = ClientStream(loop=loop, timeout=0.01,
                      send_type=DummyRequest, recv_type=DummyReply)
    with pytest.raises(ErrorDetected):
        with async_timeout.timeout(5) as safety_timeout:
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
                await asyncio.wait_for(task, timeout=1, loop=loop)
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
                await asyncio.wait_for(task, timeout=1, loop=loop)
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
    with pytest.raises(ErrorDetected):
        async with cs.client_stream as stream:
            await stream.send_request()

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            cs.client_conn.server_h2c.send_headers(stream_id, [
                (':status', '200'),
                ('grpc-status', str(Status.UNIMPLEMENTED.value)),
            ], end_stream=True)
            cs.client_conn.server_h2c.reset_stream(stream_id)
            cs.client_conn.server_flush()

            try:
                await stream.recv_initial_metadata()
            except GRPCError as exc:
                assert exc and exc.status == Status.UNIMPLEMENTED
                raise ErrorDetected()


@pytest.mark.asyncio
@pytest.mark.parametrize('status, grpc_status', [
    ('401', Status.UNAUTHENTICATED),
    ('404', Status.UNIMPLEMENTED),
    ('429', Status.UNAVAILABLE),
    ('508', Status.UNKNOWN),
])
async def test_non_ok_status(cs: ClientStream, status, grpc_status):
    with pytest.raises(ErrorDetected):
        async with cs.client_stream as stream:
            await stream.send_request()

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            cs.client_conn.server_h2c.send_headers(stream_id, [
                (':status', status),
            ], end_stream=True)
            cs.client_conn.server_h2c.reset_stream(stream_id)
            cs.client_conn.server_flush()

            try:
                await stream.recv_initial_metadata()
            except GRPCError as exc:
                assert exc
                assert exc.status == grpc_status
                assert exc.message == 'Received :status = {!r}'.format(status)
                raise ErrorDetected()


@pytest.mark.asyncio
async def test_missing_grpc_status(cs: ClientStream):
    with pytest.raises(ErrorDetected):
        async with cs.client_stream as stream:
            await stream.send_request()

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

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            cs.client_conn.server_h2c.send_headers(stream_id, [
                (':status', '200'),
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

            events = cs.client_conn.to_server_transport.events()
            stream_id = events[-1].stream_id

            headers = [
                (':status', '200'),
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
