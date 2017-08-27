from asyncio import Queue
from collections import namedtuple

import pytest

from h2.errors import ErrorCodes

from grpclib.enum import Status
from grpclib.server import Stream

from .protobuf.testing_pb2 import SavoysRequest, SavoysReply


SendHeaders = namedtuple('SendHeaders', 'headers, end_stream')
SendData = namedtuple('SendData', 'data, end_stream')
End = namedtuple('End', '')
Reset = namedtuple('Reset', 'error_code')


class H2StreamStub:

    def __init__(self):
        self.__headers__ = Queue()
        self.__data__ = Queue()
        self.__events__ = []

    async def recv_headers(self):
        return await self.__headers__.get()

    async def recv_data(self, size=None):
        data = await self.__data__.get()
        assert size is None or len(data) == size

    async def send_headers(self, headers, end_stream=False):
        self.__events__.append(SendHeaders(headers, end_stream))

    async def send_data(self, data, end_stream=False):
        self.__events__.append(SendData(data, end_stream))

    async def end(self):
        self.__events__.append(End())

    async def reset(self, error_code=ErrorCodes.NO_ERROR):
        self.__events__.append(Reset(error_code))


@pytest.mark.asyncio
async def test_no_response():
    stub = H2StreamStub()

    async with Stream(stub, SavoysRequest, SavoysReply):
        pass

    assert stub.__events__ == [
        SendHeaders(headers=[(':status', '200'),
                             ('grpc-status', str(Status.UNKNOWN.value)),
                             ('grpc-message', 'Empty reply')],
                    end_stream=True),
    ]


@pytest.mark.asyncio
async def test_exception():
    stub = H2StreamStub()

    async with Stream(stub, SavoysRequest, SavoysReply):
        1/0

    assert stub.__events__ == [
        SendHeaders(headers=[(':status', '200'),
                             ('grpc-status', str(Status.UNKNOWN.value)),
                             ('grpc-message', 'Internal Server Error')],
                    end_stream=True),
    ]
