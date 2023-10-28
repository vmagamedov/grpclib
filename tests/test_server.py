import asyncio

import pytest

from grpclib.server import Server


async def serve_forever(server):
    await server.start('127.0.0.1')
    await server.wait_closed()


@pytest.mark.asyncio
async def test_wait_closed(loop: asyncio.AbstractEventLoop):
    server = Server([])
    task = loop.create_task(serve_forever(server))
    done, pending = await asyncio.wait([task], timeout=0.1)
    assert pending and not done
    server.close()
    done, pending = await asyncio.wait([task], timeout=0.1)
    assert done and not pending


@pytest.mark.asyncio
async def test_close_twice():
    server = Server([])
    await server.start('127.0.0.1')
    server.close()
    server.close()
    await server.wait_closed()
