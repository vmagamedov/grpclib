import struct
import socket

from h2.config import H2Configuration
from h2.connection import H2Connection

from grpclib import client, server
from grpclib.const import Cardinality
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

    def __init__(self, *, loop):
        server_config = H2Configuration(client_side=False,
                                        header_encoding='ascii')
        self.server_h2c = H2Connection(server_config)

        self.to_server_transport = TransportStub(self.server_h2c)

        client_config = H2Configuration(client_side=True,
                                        header_encoding='ascii')
        self.client_proto = H2Protocol(client.Handler(), client_config,
                                       loop=loop)
        self.client_proto.connection_made(self.to_server_transport)

    def server_flush(self):
        self.client_proto.data_received(self.server_h2c.data_to_send())


class ClientStream:

    def __init__(self, *, loop, client_conn=None,
                 send_type=None, recv_type=None,
                 path='/foo/bar', codec=ProtoCodec(), connect_time=None,
                 timeout=None, deadline=None, metadata=None):
        self.client_conn = client_conn or ClientConn(loop=loop)

        channel = client.Channel(port=-1, loop=loop, codec=codec)
        self.client_stream = channel.request(
            path, send_type, recv_type,
            timeout=timeout, deadline=deadline, metadata=metadata,
        )
        self.client_stream._channel = ChannelStub(self.client_conn.client_proto,
                                                  connect_time=connect_time)


class ServerConn:

    def __init__(self, *, loop):
        client_config = H2Configuration(client_side=True,
                                        header_encoding='ascii')
        self.client_h2c = H2Connection(client_config)

        self.to_client_transport = TransportStub(self.client_h2c)
        self.client_h2c.initiate_connection()

        server_config = H2Configuration(client_side=False,
                                        header_encoding='ascii')
        self.server_proto = H2Protocol(DummyHandler(), server_config,
                                       loop=loop)
        self.server_proto.connection_made(self.to_client_transport)

        # complete settings exchange and clear events buffer
        self.client_flush()
        self.to_client_transport.events()

    def client_flush(self):
        self.server_proto.data_received(self.client_h2c.data_to_send())


class ServerStream:

    def __init__(self, *, loop, server_conn=None,
                 recv_type=None, send_type=None, path='/foo/bar',
                 content_type='application/grpc+proto',
                 codec=ProtoCodec(), deadline=None, metadata=None):
        self.server_conn = server_conn or ServerConn(loop=loop)

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
            Cardinality.UNARY_UNARY,
            codec,
            recv_type,
            send_type,
            deadline=deadline,
        )
        self.server_stream.metadata = metadata or {}


class ClientServer:
    server = None
    channel = None

    def __init__(self, handler_cls, stub_cls, *, loop, codec=None):
        self.handler_cls = handler_cls
        self.stub_cls = stub_cls
        self.loop = loop
        self.codec = codec

    async def __aenter__(self):
        host = '127.0.0.1'
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            _, port = s.getsockname()

        handler = self.handler_cls()
        self.server = server.Server([handler], loop=self.loop, codec=self.codec)
        await self.server.start(host, port)

        self.channel = client.Channel(host, port, loop=self.loop,
                                      codec=self.codec)
        stub = self.stub_cls(self.channel)
        return handler, stub

    async def __aexit__(self, *exc_info):
        self.server.close()
        await self.server.wait_closed()
        self.channel.close()
