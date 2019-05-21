import asyncio

from grpclib.utils import graceful_exit
from grpclib.server import Server, Stream

from .helloworld_pb2 import HelloRequest, HelloReply
from .helloworld_grpc import GreeterBase


class Greeter(GreeterBase):

    # UNARY_UNARY - simple RPC
    async def UnaryUnaryGreeting(
        self,
        stream: Stream[HelloRequest, HelloReply],
    ) -> None:
        request = await stream.recv_message()
        assert request is not None
        message = f'Hello, {request.name}!'
        await stream.send_message(HelloReply(message=message))

    # UNARY_STREAM - response streaming RPC
    async def UnaryStreamGreeting(
        self,
        stream: Stream[HelloRequest, HelloReply],
    ) -> None:
        request = await stream.recv_message()
        assert request is not None
        await stream.send_message(
            HelloReply(message=f'Hello, {request.name}!'))
        await stream.send_message(
            HelloReply(message=f'Goodbye, {request.name}!'))

    # STREAM_UNARY - request streaming RPC
    async def StreamUnaryGreeting(
        self,
        stream: Stream[HelloRequest, HelloReply],
    ) -> None:
        names = []
        async for request in stream:
            names.append(request.name)
        message = 'Hello, {}!'.format(' and '.join(names))
        await stream.send_message(HelloReply(message=message))

    # STREAM_STREAM - bidirectional streaming RPC
    async def StreamStreamGreeting(
        self,
        stream: Stream[HelloRequest, HelloReply],
    ) -> None:
        async for request in stream:
            message = f'Hello, {request.name}!'
            await stream.send_message(HelloReply(message=message))
        # Send another message to demonstrate responses are not
        # coupled to requests.
        message = 'Goodbye, all!'
        await stream.send_message(HelloReply(message=message))


async def main(*, host: str = '127.0.0.1', port: int = 50051) -> None:
    server = Server([Greeter()])
    with graceful_exit([server]):
        await server.start(host, port)
        print(f'Serving on {host}:{port}')
        await server.wait_closed()


if __name__ == '__main__':
    asyncio.run(main())
