import asyncio

from grpclib.server import Server

from . import helloworld_pb2
from . import helloworld_grpc


class Greeter(helloworld_grpc.Greeter):

    async def SayHello(self, request, context):
        # await asyncio.sleep(1)
        message = 'Hello, {}!'.format(request.name)
        return helloworld_pb2.HelloReply(message=message)


def main():
    loop = asyncio.get_event_loop()

    server = Server([Greeter()], loop=loop)

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


if __name__ == '__main__':
    main()
