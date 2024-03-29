import struct
import socket

from h2.config import H2Configuration
from h2.connection import H2Connection

from grpclib import client, server
from grpclib.const import Cardinality
from grpclib.config import Configuration
from grpclib.events import _DispatchServerEvents
from grpclib.protocol import H2Protocol
from grpclib.encoding.proto import ProtoCodec

from stubs import TransportStub, ChannelStub, DummyHandler


def grpc_encode(message, message_type=None, codec=ProtoCodec()):
    message_bin = codec.encode(message, message_type)
    header = struct.pack('?', False) + struct.pack('>I', len(message_bin))
    return header + message_bin


def grpc_decode(message_bin, message_type=None, codec=ProtoCodec()):
    message_len = struct.unpack('>I', message_bin[1:5])[0]
    assert len(message_bin) == message_len + 5
    message = codec.decode(message_bin[5:], message_type)
    return message


class ClientConn:

    def __init__(self):
        server_h2_config = H2Configuration(
            client_side=False,
            header_encoding='ascii',
        )
        self.server_h2c = H2Connection(server_h2_config)

        self.to_server_transport = TransportStub(self.server_h2c)

        client_h2_config = H2Configuration(
            client_side=True,
            header_encoding='ascii',
        )
        self.client_proto = H2Protocol(
            client.Handler(),
            Configuration().__for_test__(),
            client_h2_config,
        )
        self.client_proto.connection_made(self.to_server_transport)

    def server_flush(self):
        self.client_proto.data_received(self.server_h2c.data_to_send())


class ClientStream:

    def __init__(self, *, client_conn=None,
                 send_type=None, recv_type=None,
                 path='/foo/bar', codec=ProtoCodec(),
                 cardinality=Cardinality.UNARY_UNARY,
                 connect_time=None,
                 timeout=None, deadline=None, metadata=None):
        self.client_conn = client_conn or ClientConn()

        channel = client.Channel(port=-1, codec=codec)
        self.client_stream = channel.request(
            path, cardinality, send_type, recv_type,
            timeout=timeout, deadline=deadline, metadata=metadata,
        )
        self.client_stream._channel = ChannelStub(self.client_conn.client_proto,
                                                  connect_time=connect_time)


class ServerConn:

    def __init__(self):
        client_h2_config = H2Configuration(
            client_side=True,
            header_encoding='ascii',
        )
        self.client_h2c = H2Connection(client_h2_config)

        self.to_client_transport = TransportStub(self.client_h2c)
        self.client_h2c.initiate_connection()

        server_config = H2Configuration(
            client_side=False,
            header_encoding='ascii',
        )
        self.server_proto = H2Protocol(
            DummyHandler(),
            Configuration().__for_test__(),
            server_config,
        )
        self.server_proto.connection_made(self.to_client_transport)

        # complete settings exchange and clear events buffer
        self.client_flush()
        self.to_client_transport.events()

    def client_flush(self):
        self.server_proto.data_received(self.client_h2c.data_to_send())


class ServerStream:

    def __init__(self, *, server_conn=None,
                 recv_type=None, send_type=None, path='/foo/bar',
                 content_type='application/grpc+proto',
                 codec=ProtoCodec(), deadline=None, metadata=None):
        self.server_conn = server_conn or ServerConn()

        self.stream_id = (self.server_conn.client_h2c
                          .get_next_available_stream_id())
        self.server_conn.client_h2c.send_headers(self.stream_id, [
            (':method', 'POST'),
            (':scheme', 'http'),
            (':path', path),
            (':authority', 'test.com'),
            ('te', 'trailers'),
            ('content-type', content_type),
        ])
        self.server_conn.client_flush()

        self.server_h2s = self.server_conn.server_proto.processor.handler.stream
        assert self.server_h2s

        self.server_stream = server.Stream(
            self.server_h2s,
            path,
            Cardinality.UNARY_UNARY,
            recv_type,
            send_type,
            codec=codec,
            status_details_codec=None,
            dispatch=_DispatchServerEvents(),
            deadline=deadline,
        )
        self.server_stream.metadata = metadata or {}


class ClientServer:
    server = None
    channel = None

    def __init__(self, handler_cls, stub_cls, *, codec=None,
                 config=None):
        self.handler_cls = handler_cls
        self.stub_cls = stub_cls
        self.codec = codec
        self.config = config

    async def __aenter__(self):
        host = '127.0.0.1'
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            _, port = s.getsockname()

        handler = self.handler_cls()
        self.server = server.Server([handler], codec=self.codec)
        await self.server.start(host, port)

        self.channel = client.Channel(host, port, codec=self.codec,
                                      config=self.config)
        stub = self.stub_cls(self.channel)
        return handler, stub

    async def __aexit__(self, *exc_info):
        self.channel.close()
        self.server.close()
        await self.server.wait_closed()
