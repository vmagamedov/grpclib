import asyncio

from asyncgrpc.server import create_server

import helloworld_pb2
import helloworld_grpc_pb2


class Greeter(helloworld_grpc_pb2.Greeter):

    async def SayHello(self, request, context):
        await asyncio.sleep(1)
        message = 'Hello, {}!'.format(request.name)
        return helloworld_pb2.HelloReply(message=message)


def main():
    loop = asyncio.get_event_loop()

    server = loop.run_until_complete(create_server([Greeter()], loop=loop))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    server.close()
    loop.run_until_complete(server.wait_closed())
    loop.close()


if __name__ == '__main__':
    main()
