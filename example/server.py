import asyncio

from asyncgrpc.server import Method, create_server

import helloworld_pb2


async def say_hello(request):
    await asyncio.sleep(1)
    return helloworld_pb2.HelloReply(message='Hello, {}!'.format(request.name))


def main():
    loop = asyncio.get_event_loop()

    mapping = {
        '/helloworld.Greeter/SayHello': Method(
            say_hello,
            helloworld_pb2.HelloRequest,
            helloworld_pb2.HelloReply,
        )
    }

    server = loop.run_until_complete(create_server(mapping, loop=loop))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    server.close()
    loop.run_until_complete(server.wait_closed())
    loop.close()


if __name__ == '__main__':
    main()
