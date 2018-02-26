import asyncio

from grpclib.server import Server

from .helloworld_pb2 import HelloReply
from .helloworld_grpc import GreeterBase


class Greeter(GreeterBase):

    # UNARY_UNARY - simple RPC
    async def SayHello(self, stream):
        request = await stream.recv_message()
        message = 'Hello, {}!'.format(request.name)
        await stream.send_message(HelloReply(message=message))

    # UNARY_STREAM - response streaming RPC
    async def SayHelloGoodbye(self, stream):
        request = await stream.recv_message()
        await stream.send_message(
            HelloReply(message='Hello, {}!'.format(request.name)))
        await stream.send_message(
            HelloReply(message='Goodbye, {}!'.format(request.name)))

    # STREAM_UNARY - request streaming RPC
    async def SayHelloToMany(self, stream):
        async for request in stream:
            message = 'Hello, {}!'.format(request.name)
            await stream.send_message(HelloReply(message=message))
        await stream.send_trailing_metadata()

    # STREAM_STREAM - bidirectional streaming RPC
    async def SayHelloToManyAtOnce(self, stream):
        async for request in stream:
            message = 'Hello, {}!'.format(request.name)
        message = 'Goodbye, {}!'.format(request.name)
        await stream.send_message(HelloReply(message=message), end=True)


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
