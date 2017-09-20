import asyncio

from grpclib.client import Channel

from .helloworld_pb2 import HelloRequest
from .helloworld_grpc import GreeterStub


async def main():
    channel = Channel(loop=asyncio.get_event_loop())
    stub = GreeterStub(channel)

    print(await stub.SayHello(HelloRequest(name='World')))


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
