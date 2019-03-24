import asyncio

from grpclib.utils import graceful_exit
from grpclib.server import Server
from grpclib.server import Stream

from .helloworld_pb2 import HelloReply, HelloRequest
from .helloworld_grpc import GreeterBase


class Greeter(GreeterBase):

    async def SayHello(self, stream: Stream[HelloRequest, HelloReply]) -> None:
        request = await stream.recv_message()
        message = 'Hello, {}!'.format(request.name)
        await stream.send_message(HelloReply(message=message))


async def main(*, host: str = '127.0.0.1', port: int = 50051) -> None:
    loop = asyncio.get_running_loop()
    server = Server([Greeter()], loop=loop)
    with graceful_exit([server], loop=loop):
        await server.start(host, port)
        print(f'Serving on {host}:{port}')
        await server.wait_closed()


if __name__ == '__main__':
    asyncio.run(main())
