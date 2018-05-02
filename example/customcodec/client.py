import asyncio
from grpclib.client import Channel
import grpclib
from .codec import JSONCodec


class GreeterStub:

    def __init__(self, channel):
        self.UnaryUnaryGreeting = grpclib.client.UnaryUnaryMethod(
            channel,
            '/HelloWorld/UnaryUnaryGreeting',
            None,
            None
        )


async def main():    
    channel = Channel(loop=asyncio.get_event_loop(), codec=JSONCodec)
    stub = GreeterStub(channel)
    
    print('Demonstrating UNARY_UNARY')

    # Demonstrate simple case where requests are known before interaction
    print(await stub.UnaryUnaryGreeting({'name': 'you'}))

    # This block performs the same UNARY_UNARY interaction as above
    # while showing more advanced stream control features.
    async with stub.UnaryUnaryGreeting.open() as stream:
        await stream.send_message({'name': 'you'})
        reply = await stream.recv_message()
        print(reply)


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
