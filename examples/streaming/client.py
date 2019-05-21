import asyncio

from grpclib.client import Channel

from .helloworld_pb2 import HelloRequest
from .helloworld_grpc import GreeterStub


async def main() -> None:
    channel = Channel()
    stub = GreeterStub(channel)

    # ------------------------------------------------------------------------
    # UNARY_UNARY RPC

    print('Demonstrating UNARY_UNARY')

    # Demonstrate simple case where requests are known before interaction
    print(await stub.UnaryUnaryGreeting(HelloRequest(name='you')))

    # This block performs the same UNARY_UNARY interaction as above
    # while showing more advanced stream control features.
    async with stub.UnaryUnaryGreeting.open() as stream:
        await stream.send_message(HelloRequest(name='yall'))
        reply = await stream.recv_message()
        print(reply)

    # ------------------------------------------------------------------------
    # UNARY_STREAM RPC

    print('Demonstrating UNARY_STREAM')

    # Demonstrate simple case where requests are known before interaction
    print(await stub.UnaryStreamGreeting(HelloRequest(name='you')))

    # This block performs the same UNARY_STREAM interaction as above
    # while showing more advanced stream control features.
    async with stub.UnaryStreamGreeting.open() as stream:
        await stream.send_message(HelloRequest(name='yall'), end=True)
        replies = [reply async for reply in stream]
        print(replies)

    # ------------------------------------------------------------------------
    # STREAM_UNARY RPC

    print('Demonstrating STREAM_UNARY')

    # Demonstrate simple case where requests are known before interaction
    msgs = [HelloRequest(name='Rick'), HelloRequest(name='Morty')]
    print(await stub.StreamUnaryGreeting(msgs))

    # This block performs the same STREAM_UNARY interaction as above
    # while showing more advanced stream control features.
    async with stub.StreamUnaryGreeting.open() as stream:
        for msg in msgs:
            await stream.send_message(msg)
        await stream.end()
        reply = await stream.recv_message()
        print(reply)

    # ------------------------------------------------------------------------
    # STREAM_STREAM RPC

    print('Demonstrating STREAM_STREAM')

    # Demonstrate simple case where requests are known before interaction
    msgs = [HelloRequest(name='Rick'), HelloRequest(name='Morty')]
    print(await stub.StreamStreamGreeting(msgs))

    channel.close()


if __name__ == '__main__':
    asyncio.run(main())
