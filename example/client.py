import sys
import asyncio

from asyncgrpc.client import Channel

from helloworld_pb2 import HelloRequest
from helloworld_pb2_grpc import GreeterStub


async def main(*, loop):
    name = sys.argv[1] if len(sys.argv) > 1 else 'World'

    channel = Channel(loop=loop)
    stub = GreeterStub(channel)

    hello_reply = await stub.SayHello(HelloRequest(name=name))
    print(hello_reply)


if __name__ == '__main__':
    _loop = asyncio.get_event_loop()
    _loop.run_until_complete(main(loop=_loop))
