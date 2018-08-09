import asyncio

from grpclib.server import Server

from .helloworld_pb2 import HelloReply
from .helloworld_grpc import GreeterBase


class Greeter(GreeterBase):

    # UNARY_UNARY - simple RPC
    async def UnaryUnaryGreeting(self, stream):
        request = await stream.recv_message()
        message = 'Hello, {}!'.format(request.name)
        await stream.send_message(HelloReply(message=message))

    # UNARY_STREAM - response streaming RPC
    async def UnaryStreamGreeting(self, stream):
        request = await stream.recv_message()
        await stream.send_message(
            HelloReply(message='Hello, {}!'.format(request.name)))
        await stream.send_message(
            HelloReply(message='Goodbye, {}!'.format(request.name)))

    # STREAM_UNARY - request streaming RPC
    async def StreamUnaryGreeting(self, stream):
        names = []
        async for request in stream:
            names.append(request.name)
        message = 'Hello, {}!'.format(' and '.join(names))
        await stream.send_message(HelloReply(message=message))

    # STREAM_STREAM - bidirectional streaming RPC
    async def StreamStreamGreeting(self, stream):
        async for request in stream:
            message = 'Hello, {}!'.format(request.name)
            await stream.send_message(HelloReply(message=message))
        # Send another message to demonstrate responses are not
        # coupled to requests.
        message = 'Goodbye, all!'
        await stream.send_message(HelloReply(message=message))


def run(server, *, loop):
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


def main():
    loop = asyncio.get_event_loop()
    server = Server([Greeter()], loop=loop)
    run(server, loop=loop)


if __name__ == '__main__':
    main()
