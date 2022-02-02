import gc
import asyncio.tasks

import pytest

from grpclib.const import Status
from grpclib.testing import ChannelFor
from grpclib.exceptions import GRPCError

from conn import ClientServer
from dummy_pb2 import DummyRequest, DummyReply
from dummy_grpc import DummyServiceBase, DummyServiceStub


class DummyService(DummyServiceBase):

    async def UnaryUnary(self, stream):
        request = await stream.recv_message()
        assert request == DummyRequest(value='ping')
        await stream.send_message(DummyReply(value='pong'))

    async def UnaryStream(self, stream):
        raise GRPCError(Status.UNIMPLEMENTED)

    async def StreamUnary(self, stream):
        raise GRPCError(Status.UNIMPLEMENTED)

    async def StreamStream(self, stream):
        raise GRPCError(Status.UNIMPLEMENTED)


def collect():
    objects = gc.get_objects()
    return {id(obj): obj for obj in objects}


def _check(type_name):
    """Utility function to debug references"""
    import objgraph

    objects = objgraph.by_type(type_name)
    if objects:
        obj = objects[0]
        objgraph.show_backrefs(obj, max_depth=3, filename='graph.png')


def test_connection():
    loop = asyncio.new_event_loop()

    async def example():
        async with ChannelFor([DummyService()]) as channel:
            stub = DummyServiceStub(channel)
            await stub.UnaryUnary(DummyRequest(value='ping'))

    # warm up
    loop.run_until_complete(example())

    gc.collect()
    gc.disable()
    try:
        pre = set(collect())
        loop.run_until_complete(example())
        loop.stop()
        loop.close()
        post = collect()

        diff = set(post).difference(pre)
        diff.discard(id(pre))
        diff.discard(id(asyncio.tasks._current_tasks))
        if diff:
            for i in diff:
                try:
                    print(post[i])
                except Exception:
                    print('...')
            raise AssertionError('Memory leak detected')
    finally:
        gc.enable()


@pytest.mark.asyncio
async def test_stream():
    cs = ClientServer(DummyService, DummyServiceStub)
    async with cs as (_, stub):
        await stub.UnaryUnary(DummyRequest(value='ping'))
        handler = next(iter(cs.server._handlers))
        handler.__gc_collect__()
        gc.collect()
        gc.disable()
        try:
            pre = set(collect())
            await stub.UnaryUnary(DummyRequest(value='ping'))
            handler.__gc_collect__()
            post = collect()

            diff = set(post).difference(pre)
            diff.discard(id(pre))
            for i in diff:
                try:
                    print(repr(post[i])[:120])
                except Exception:
                    print('...')
                else:
                    if 'grpclib.' in repr(post[i]):
                        raise AssertionError('Memory leak detected')
        finally:
            gc.enable()
