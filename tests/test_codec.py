import json

import pytest

import grpclib.const
import grpclib.server

from grpclib.client import UnaryUnaryMethod
from grpclib.events import _DispatchServerEvents
from grpclib.exceptions import GRPCError
from grpclib.encoding.base import CodecBase

from conn import ClientStream, ClientServer, ServerStream
from conn import grpc_encode, grpc_decode


class JSONCodec(CodecBase):
    __content_subtype__ = 'json'

    def encode(self, message, message_type):
        return json.dumps(message, ensure_ascii=False).encode('utf-8')

    def decode(self, data: bytes, message_type):
        return json.loads(data.decode('utf-8'))


class PingServiceHandler:

    async def UnaryUnary(self, stream):
        request = await stream.recv_message()
        assert request == {'value': 'ping'}
        await stream.send_message({'value': 'pong'})

    def __mapping__(self):
        return {
            '/ping.PingService/UnaryUnary': grpclib.const.Handler(
                self.UnaryUnary,
                grpclib.const.Cardinality.UNARY_UNARY,
                None,
                None,
            ),
        }


class PingServiceStub:

    def __init__(self, channel):
        self.UnaryUnary = UnaryUnaryMethod(
            channel,
            '/ping.PingService/UnaryUnary',
            None,
            None,
        )


@pytest.mark.asyncio
async def test_rpc_call(loop):
    ctx = ClientServer(PingServiceHandler, PingServiceStub, loop=loop,
                       codec=JSONCodec())
    async with ctx as (handler, stub):
        reply = await stub.UnaryUnary({'value': 'ping'})
        assert reply == {'value': 'pong'}


@pytest.mark.asyncio
async def test_client_receive_json(loop):
    cs = ClientStream(loop=loop, codec=JSONCodec())

    async with cs.client_stream as stream:
        await stream.send_request()
        _, request_received = cs.client_conn.to_server_transport.events()
        await stream.send_message({'value': 'ping'}, end=True)

        content_type = dict(request_received.headers)['content-type']
        assert content_type == 'application/grpc+json'

        cs.client_conn.server_h2c.send_headers(
            request_received.stream_id,
            [
                (':status', '200'),
                ('content-type', 'application/grpc+json'),
            ],
        )
        cs.client_conn.server_h2c.send_data(
            request_received.stream_id,
            grpc_encode({'value': 'pong'}, None, JSONCodec()),
        )
        cs.client_conn.server_h2c.send_headers(
            request_received.stream_id,
            [
                ('grpc-status', str(grpclib.const.Status.OK.value)),
            ],
            end_stream=True,
        )
        cs.client_conn.server_flush()

        reply = await stream.recv_message()
        assert reply == {'value': 'pong'}


@pytest.mark.asyncio
async def test_client_receive_invalid(loop):
    cs = ClientStream(loop=loop, codec=JSONCodec())
    with pytest.raises(GRPCError) as exc:
        async with cs.client_stream as stream:
            await stream.send_request()
            _, request_received = cs.client_conn.to_server_transport.events()

            content_type = dict(request_received.headers)['content-type']
            assert content_type == 'application/grpc+json'

            cs.client_conn.server_h2c.send_headers(
                request_received.stream_id,
                [
                    (':status', '200'),
                    ('content-type', 'application/grpc+proto'),
                ],
            )
            cs.client_conn.server_h2c.send_data(
                request_received.stream_id,
                grpc_encode({'value': 'pong'}, None, JSONCodec()),
            )
            cs.client_conn.server_h2c.send_headers(
                request_received.stream_id,
                [
                    ('grpc-status', str(grpclib.const.Status.OK.value)),
                ],
                end_stream=True,
            )
            cs.client_conn.server_flush()

            await stream.recv_message()
    exc.match(r"Invalid content-type: 'application/grpc\+proto'")


@pytest.mark.asyncio
async def test_server_receive_json(loop):
    handler = PingServiceHandler()
    mapping = handler.__mapping__()
    path = next(iter(mapping.keys()))
    ss = ServerStream(loop=loop, codec=JSONCodec(), path=path,
                      content_type='application/grpc+json')
    ss.server_conn.client_h2c.send_data(
        ss.stream_id,
        grpc_encode({'value': 'ping'}, None, JSONCodec()),
        end_stream=True,
    )
    ss.server_conn.client_flush()
    await grpclib.server.request_handler(
        handler.__mapping__(),
        ss.server_h2s,
        ss.server_conn.server_proto.processor.handler.headers,
        JSONCodec(),
        _DispatchServerEvents(),
        lambda: None,
    )
    response_received, data_received, trailers_received, _ = \
        ss.server_conn.to_client_transport.events()

    assert dict(response_received.headers)[':status'] == '200'
    assert dict(response_received.headers)['content-type'] == \
        'application/grpc+json'

    reply = grpc_decode(data_received.data, None, JSONCodec())
    assert reply == {'value': 'pong'}

    assert dict(trailers_received.headers)['grpc-status'] == '0'


@pytest.mark.asyncio
async def test_server_receive_invalid(loop):
    handler = PingServiceHandler()
    mapping = handler.__mapping__()
    path = next(iter(mapping.keys()))
    ss = ServerStream(loop=loop, codec=JSONCodec(), path=path,
                      content_type='application/grpc+invalid')
    ss.server_conn.client_h2c.send_data(
        ss.stream_id,
        grpc_encode({'value': 'ping'}, None, JSONCodec()),
        end_stream=True,
    )
    ss.server_conn.client_flush()
    await grpclib.server.request_handler(
        handler.__mapping__(),
        ss.server_h2s,
        ss.server_conn.server_proto.processor.handler.headers,
        JSONCodec(),
        _DispatchServerEvents(),
        lambda: None,
    )
    response_received, _ = ss.server_conn.to_client_transport.events()

    assert dict(response_received.headers)[':status'] == '415'
    assert dict(response_received.headers)['grpc-status'] == '2'
    assert dict(response_received.headers)['grpc-message'] == \
        'Unacceptable content-type header'


@pytest.mark.asyncio
async def test_server_return_json(loop):
    ss = ServerStream(loop=loop, codec=JSONCodec())
    ss.server_conn.client_h2c.send_data(
        ss.stream_id,
        grpc_encode({'value': 'ping'}, None, JSONCodec()),
        end_stream=True,
    )
    ss.server_conn.client_flush()

    message = await ss.server_stream.recv_message()
    assert message == {'value': 'ping'}

    await ss.server_stream.send_initial_metadata()
    response_received, = ss.server_conn.to_client_transport.events()
    content_type = dict(response_received.headers)['content-type']
    assert content_type == 'application/grpc+json'

    await ss.server_stream.send_message({'value': 'pong'})
    data_received, = ss.server_conn.to_client_transport.events()

    reply = grpc_decode(data_received.data, None, JSONCodec())
    assert reply == {'value': 'pong'}
