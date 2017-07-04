import os
import time
import asyncio

from asyncgrpc.client import Channel

from .helloworld_pb2 import HelloRequest
from .helloworld_grpc import GreeterStub


async def main(*, loop):
    channel = Channel(loop=loop)
    stub = GreeterStub(channel)

    print(await stub.SayHello(HelloRequest(name='World')))


async def bench(concurrency, *, loop):
    count = 1000
    real_count = (count // concurrency) * concurrency
    channel = Channel(loop=loop)
    stub = GreeterStub(channel)

    async def worker():
        for i in range(count // concurrency):
            await stub.SayHello(HelloRequest(name='World'))

    t1 = time.time()
    tasks = [loop.create_task(worker())
             for _ in range(concurrency)]
    await asyncio.wait(tasks)
    t2 = time.time()
    print('{} rps ({} requests)'.format(int(real_count / (t2 - t1)),
                                        real_count))


if __name__ == '__main__':
    _loop = asyncio.get_event_loop()
    if 'BENCH' not in os.environ:
        _loop.run_until_complete(main(loop=_loop))
    else:
        concurrency = int(os.environ['BENCH'])
        _loop.run_until_complete(bench(concurrency, loop=_loop))
