import asyncio

from grpclib.server import Server

from .helloworld_pb2 import HelloReply
from .helloworld_grpc import GreeterBase


class Greeter(GreeterBase):

    async def SayHello(self, stream):
        request = await stream.recv()
        message = 'Hello, {}!'.format(request.name)
        await stream.send(HelloReply(message=message))


def main():
    loop = asyncio.get_event_loop()

    server = Server([Greeter()], loop=loop)

    host, port = '127.0.0.1', 50051
    loop.run_until_complete(server.start(host, port))
    print('Serving on {}:{}'.format(host, port))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    server.close()
    loop.run_until_complete(server.wait_closed())
    loop.close()


if __name__ == '__main__':
    main()
