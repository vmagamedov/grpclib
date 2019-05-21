import asyncio
import contextvars

from typing import Optional, cast

from grpclib.utils import graceful_exit
from grpclib.server import Server, Stream
from grpclib.events import listen, RecvRequest

from helloworld.helloworld_pb2 import HelloRequest, HelloReply
from helloworld.helloworld_grpc import GreeterBase


XRequestId = Optional[str]

request_id: contextvars.ContextVar[XRequestId] = \
    contextvars.ContextVar('x-request-id')


class Greeter(GreeterBase):

    async def SayHello(self, stream: Stream[HelloRequest, HelloReply]) -> None:
        print(f'Current Request ID: {request_id.get()}')
        request = await stream.recv_message()
        assert request is not None
        message = f'Hello, {request.name}!'
        await stream.send_message(HelloReply(message=message))


async def on_recv_request(event: RecvRequest) -> None:
    r_id = cast(XRequestId, event.metadata.get('x-request-id'))
    request_id.set(r_id)


async def main(*, host: str = '127.0.0.1', port: int = 50051) -> None:
    server = Server([Greeter()])
    listen(server, RecvRequest, on_recv_request)
    with graceful_exit([server]):
        await server.start(host, port)
        print(f'Serving on {host}:{port}')
        await server.wait_closed()


if __name__ == '__main__':
    asyncio.run(main())
