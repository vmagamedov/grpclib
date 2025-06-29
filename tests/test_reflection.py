import socket

from google.protobuf.descriptor_pool import DescriptorPool

import pytest
import pytest_asyncio

from google.protobuf.descriptor_pb2 import FileDescriptorProto

from grpclib.client import Channel
from grpclib.server import Server
from grpclib.reflection.service import ServerReflection
from grpclib.reflection.v1.reflection_pb2 import ServerReflectionRequest
from grpclib.reflection.v1.reflection_pb2 import ServerReflectionResponse
from grpclib.reflection.v1.reflection_pb2 import ErrorResponse
from grpclib.reflection.v1.reflection_grpc import ServerReflectionStub

from dummy_pb2 import DESCRIPTOR
from test_functional import DummyService


@pytest.fixture(name='port')
def port_fixture():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        _, port = s.getsockname()
    return port


@pytest_asyncio.fixture(name='channel')
async def channel_fixture(port):
    services = [DummyService()]
    services = ServerReflection.extend(services)

    server = Server(services)
    await server.start(port=port)

    channel = Channel(port=port)
    try:
        yield channel
    finally:
        channel.close()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_file_by_filename_response(channel):
    r1, r2 = await ServerReflectionStub(channel).ServerReflectionInfo([
        ServerReflectionRequest(
            file_by_filename=DESCRIPTOR.name,
        ),
        ServerReflectionRequest(
            file_by_filename='my/missing.proto',
        ),
    ])

    proto_bytes, = r1.file_descriptor_response.file_descriptor_proto
    dummy_proto = FileDescriptorProto()
    dummy_proto.ParseFromString(proto_bytes)
    assert dummy_proto.name == DESCRIPTOR.name
    assert dummy_proto.package == DESCRIPTOR.package

    assert r2 == ServerReflectionResponse(
        error_response=ErrorResponse(
            error_code=5,
            error_message='not found',
        ),
    )


@pytest.mark.asyncio
async def test_file_containing_symbol_response(channel):
    r1, r2 = await ServerReflectionStub(channel).ServerReflectionInfo([
        ServerReflectionRequest(
            file_containing_symbol=(
                DESCRIPTOR.message_types_by_name['DummyRequest'].full_name
            ),
        ),
        ServerReflectionRequest(
            file_containing_symbol='unknown.Symbol',
        ),
    ])

    proto_bytes, = r1.file_descriptor_response.file_descriptor_proto
    dummy_proto = FileDescriptorProto()
    dummy_proto.ParseFromString(proto_bytes)
    assert dummy_proto.name == DESCRIPTOR.name
    assert dummy_proto.package == DESCRIPTOR.package

    assert r2 == ServerReflectionResponse(
        error_response=ErrorResponse(
            error_code=5,
            error_message='not found',
        ),
    )


def test_all_extension_numbers_of_type_response():
    pass  # message extension is a deprecated feature and not exist in proto3


@pytest.mark.asyncio
async def test_list_services_response(channel):
    r1, = await ServerReflectionStub(channel).ServerReflectionInfo([
        ServerReflectionRequest(
            list_services='',
        ),
    ])

    service, = r1.list_services_response.service
    assert service.name == DESCRIPTOR.services_by_name['DummyService'].full_name


@pytest.mark.asyncio
async def test_file_containing_symbol_response_custom_pool(port):
    my_pool = DescriptorPool()
    services = [DummyService()]
    services = ServerReflection.extend(services, pool=my_pool)

    server = Server(services)
    await server.start(port=port)

    channel = Channel(port=port)
    try:
        # because we use our own pool (my_pool), there's no descriptors to find.
        req = ServerReflectionRequest(
            file_containing_symbol=(
                DESCRIPTOR.message_types_by_name['DummyRequest'].full_name
            ),
        )
        resp, = await ServerReflectionStub(channel).ServerReflectionInfo([req])

        assert resp == ServerReflectionResponse(
            error_response=ErrorResponse(
                error_code=5,
                error_message='not found',
            ),
        )

        # once we update the pool, we should find the descriptor.
        my_pool.AddSerializedFile(DESCRIPTOR.serialized_pb)

        resp, = await ServerReflectionStub(channel).ServerReflectionInfo([req])

        proto_bytes, = resp.file_descriptor_response.file_descriptor_proto
        dummy_proto = FileDescriptorProto()
        dummy_proto.ParseFromString(proto_bytes)
        assert dummy_proto.name == DESCRIPTOR.name
        assert dummy_proto.package == DESCRIPTOR.package
    finally:
        channel.close()
        server.close()
        await server.wait_closed()
