import ssl
import asyncio
import tempfile
import contextlib
from unittest.mock import patch, ANY

import pytest
import certifi
from h2.connection import H2Connection

import grpclib.client
from grpclib.client import Channel, Handler
from grpclib.config import Configuration
from grpclib.protocol import H2Protocol
from grpclib.testing import ChannelFor

from dummy_pb2 import DummyRequest, DummyReply
from dummy_grpc import DummyServiceStub
from test_functional import DummyService
from stubs import TransportStub


@pytest.mark.asyncio
async def test_concurrent_connect(loop):
    count = 5
    reqs = [DummyRequest(value="ping") for _ in range(count)]
    reps = [DummyReply(value="pong") for _ in range(count)]

    channel = Channel()

    async def create_connection(*args, **kwargs):
        await asyncio.sleep(0.01)
        return None, _channel._protocol

    stub = DummyServiceStub(channel)
    async with ChannelFor([DummyService()]) as _channel:
        with patch.object(loop, "create_connection") as po:
            po.side_effect = create_connection
            tasks = [loop.create_task(stub.UnaryUnary(req)) for req in reqs]
            replies = await asyncio.gather(*tasks)
    assert replies == reps
    po.assert_awaited_once_with(
        ANY,
        "127.0.0.1",
        50051,
        ssl=None,
        server_hostname=None,
    )


@pytest.mark.asyncio
async def test_default_ssl_context():
    with patch.object(certifi, "where", return_value=certifi.where()) as po:
        certifi_channel = Channel(ssl=True)
        assert certifi_channel._ssl
        po.assert_called_once()

    with patch.object(certifi, "where", side_effect=AssertionError):
        with patch.dict("sys.modules", {"certifi": None}):
            system_channel = Channel(ssl=True)
            assert system_channel._ssl


@pytest.mark.asyncio
async def test_ssl_target_name_override(loop):
    config = Configuration(ssl_target_name_override="example.com")

    async def create_connection(*args, **kwargs):
        h2_conn = H2Connection()
        transport = TransportStub(h2_conn)
        protocol = H2Protocol(Handler(), config.__for_test__(), h2_conn.config)
        protocol.connection_made(transport)
        return None, protocol

    with patch.object(loop, "create_connection") as po:
        po.side_effect = create_connection
        async with Channel(ssl=True, config=config) as channel:
            await channel.__connect__()
            po.assert_awaited_once_with(
                ANY, ANY, ANY, ssl=channel._ssl, server_hostname="example.com"
            )


@pytest.mark.asyncio
async def test_default_verify_paths():
    with contextlib.ExitStack() as cm:
        tf = cm.enter_context(tempfile.NamedTemporaryFile()).name
        td = cm.enter_context(tempfile.TemporaryDirectory())
        po = cm.enter_context(
            patch.object(ssl.SSLContext, "load_verify_locations"),
        )
        cm.enter_context(
            patch.dict("os.environ", SSL_CERT_FILE=tf, SSL_CERT_DIR=td),
        )
        default_verify_paths = ssl.get_default_verify_paths()
        channel = Channel(ssl=default_verify_paths)
        assert channel._ssl
        po.assert_called_once_with(tf, td, None)
        assert default_verify_paths.openssl_cafile_env == "SSL_CERT_FILE"
        assert default_verify_paths.openssl_capath_env == "SSL_CERT_DIR"


@pytest.mark.asyncio
async def test_no_ssl_support():
    with patch.object(grpclib.client, "_ssl", None):
        Channel()
        with pytest.raises(RuntimeError) as err:
            Channel(ssl=True)
        err.match("SSL is not supported")
