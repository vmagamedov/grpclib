import uuid
import asyncio

from grpclib.client import Channel
from grpclib.events import listen, SendRequest

from helloworld.helloworld_pb2 import HelloRequest
from helloworld.helloworld_grpc import GreeterStub


async def on_send_request(event: SendRequest) -> None:
    request_id = event.metadata['x-request-id'] = str(uuid.uuid4())
    print(f'Generated Request ID: {request_id}')


async def main() -> None:
    channel = Channel('127.0.0.1', 50051)
    listen(channel, SendRequest, on_send_request)

    stub = GreeterStub(channel)
    response = await stub.SayHello(HelloRequest(name='World'))
    print(response.message)

    channel.close()


if __name__ == '__main__':
    asyncio.run(main())
