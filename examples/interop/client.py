import asyncio

from grpclib.interop import InteropChannel

from helloworld.helloworld_pb2 import HelloRequest, HelloReply
from helloworld.helloworld_pb2_grpc import GreeterStub


async def main():
    channel = InteropChannel('127.0.0.1', 50051)
    stub = GreeterStub(channel)

    reply: HelloReply = await stub.SayHello(HelloRequest(name='Dr. Strange'))
    print(reply.message)

    channel.close()


if __name__ == '__main__':
    asyncio.run(main())
