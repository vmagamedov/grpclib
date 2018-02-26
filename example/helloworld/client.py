import asyncio

from grpclib.client import Channel

from .helloworld_pb2 import HelloRequest
from .helloworld_grpc import GreeterStub


async def main():
    channel = Channel(loop=asyncio.get_event_loop())
    stub = GreeterStub(channel)

    # UNARY_UNARY - simple RPC
    print(await stub.SayHello(HelloRequest(name='you')))
    async with stub.SayHello.open() as stream:
        await stream.send_message(HelloRequest(name='yall'))
        reply = await stream.recv_message()
        print(reply)

    # UNARY_STREAM - response streaming RPC
    print(await stub.SayHelloGoodbye(HelloRequest(name='yall')))
    async with stub.SayHelloGoodbye.open() as stream:
        await stream.send_message(HelloRequest(name='yall'), end=True)
        replies = [reply async for reply in stream]
        print(replies)

    # STREAM_UNARY - request streaming RPC.
    msgs = [HelloRequest(name='Rick'), HelloRequest(name='Morty')]
    print(await stub.SayHelloToManyAtOnce(msgs))
    async with stub.SayHelloToManyAtOnce.open() as stream:
        for msg in msgs:
            last_msg = msg == msgs[-1]
            await stream.send_message(msg, end=last_msg)
        reply = await stream.recv_message()
        print(reply)

    # STREAM_STREAM - bidirectional streaming RPC
    msgs = [HelloRequest(name='Rick'), HelloRequest(name='Morty')]
    print(await stub.SayHelloToMany(msgs))


if __name__ == '__main__':
    asyncio.get_event_loop().run_until_complete(main())
