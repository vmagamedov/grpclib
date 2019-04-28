import asyncio
import contextvars

from grpclib.utils import graceful_exit
from grpclib.server import Server
from grpclib.events import listen, RecvRequest

from helloworld.helloworld_pb2 import HelloReply
from helloworld.helloworld_grpc import GreeterBase


request_id = contextvars.ContextVar('x-request-id')


class Greeter(GreeterBase):

    async def SayHello(self, stream):
        print(f'Current Request ID: {request_id.get()}')
        request = await stream.recv_message()
        message = f'Hello, {request.name}!'
        await stream.send_message(HelloReply(message=message))


async def recv_request(event: RecvRequest):
    r_id = event.metadata.get('x-request-id')
    request_id.set(r_id)


async def main(*, host='127.0.0.1', port=50051):
    loop = asyncio.get_running_loop()
    server = Server([Greeter()], loop=loop)
    listen(server, RecvRequest, recv_request)
    with graceful_exit([server], loop=loop):
        await server.start(host, port)
        print(f'Serving on {host}:{port}')
        await server.wait_closed()


if __name__ == '__main__':
    asyncio.run(main())
