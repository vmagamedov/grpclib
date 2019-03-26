import asyncio

from grpclib.client import Channel
from grpclib.utils import none_throws

from .helloworld_pb2 import HelloRequest
from .helloworld_grpc import GreeterStub


async def main() -> None:
    loop = asyncio.get_event_loop()
    channel = Channel('127.0.0.1', 50051, loop=loop)
    stub = GreeterStub(channel)

    response = none_throws(await stub.SayHello(HelloRequest(name='World')))
    print(response.message)

    channel.close()


if __name__ == '__main__':
    asyncio.run(main())
