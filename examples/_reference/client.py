import asyncio

import grpc.experimental.aio as grpc_aio

from helloworld import helloworld_pb2
from helloworld import helloworld_pb2_grpc


async def main():
    async with grpc_aio.insecure_channel('127.0.0.1:50051') as channel:
        stub = helloworld_pb2_grpc.GreeterStub(channel)
        reply = await stub.SayHello(helloworld_pb2.HelloRequest(name='World'))
        print(reply)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
