import time
import asyncio

from asyncgrpc.client import Channel

from .helloworld_pb2 import HelloRequest
from .helloworld_grpc import GreeterStub


async def main1(*, loop):
    channel = Channel(loop=loop)
    stub = GreeterStub(channel)

    print(await stub.SayHello(HelloRequest(name='World')))

async def main2(*, loop):
    channel = Channel(loop=loop)
    stub = GreeterStub(channel)

    t1 = time.time()
    for i in range(1000):
        await stub.SayHello(HelloRequest(name='World'))
    t2 = time.time()
    print('{} rps'.format(int(1000 / (t2 - t1))))


async def main3(*, loop):
    channel = Channel(loop=loop)
    stub = GreeterStub(channel)

    async def worker():
        for i in range(100):
            await stub.SayHello(HelloRequest(name='World'))

    t1 = time.time()
    tasks = [loop.create_task(worker())
             for _ in range(10)]
    await asyncio.wait(tasks)
    t2 = time.time()
    print('{} rps'.format(int(1000 / (t2 - t1))))


if __name__ == '__main__':
    _loop = asyncio.get_event_loop()
    _loop.run_until_complete(main1(loop=_loop))
