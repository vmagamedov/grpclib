import asyncio

from concurrent.futures import ThreadPoolExecutor

import grpc

from asyncgrpc.handler import implements, create_handler

from helloworld_pb2 import HelloReply
from helloworld_pb2_asyncgrpc import Greeter


@implements(Greeter.SayHello)
async def hello(message, context, *, loop):
    await asyncio.sleep(1, loop=loop)  # simulates async operation
    return HelloReply(message='Hello, {}!'.format(message.name))


def main():
    loop = asyncio.get_event_loop()

    functions = [hello]
    dependencies = {'loop': loop}

    server = grpc.server(ThreadPoolExecutor(max_workers=10), [
        create_handler(Greeter, dependencies, functions, loop=loop),
    ])
    server.add_insecure_port('[::]:50051')
    server.start()
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        server.stop(0)


if __name__ == '__main__':
    main()
