import json

import pytest

import grpclib.const
import grpclib.server

from conn import ClientStream, ClientServer, grpc_encode
from grpclib.client import Channel, UnaryUnaryMethod
from grpclib.exceptions import GRPCError
from grpclib.encoding.base import CodecBase


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

    def __init__(self, channel: Channel) -> None:
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
async def test_client_stream(loop):
    cs = ClientStream(loop=loop, codec=JSONCodec())

    async with cs.client_stream as stream:
        await stream.send_request()
        _, request_received = cs.client_conn.to_server_transport.events()

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
async def test_client_stream_and_invalid_content_type(loop):
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
    exc.match("Invalid content-type: 'application/grpc\+proto'")
