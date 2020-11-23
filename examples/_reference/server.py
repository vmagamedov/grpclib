import asyncio

import grpc.aio

from helloworld import helloworld_pb2
from helloworld import helloworld_pb2_grpc


class Greeter(helloworld_pb2_grpc.GreeterServicer):

    async def SayHello(self, request, context):
        return helloworld_pb2.HelloReply(message='Hello, %s!' % request.name)


async def serve(host='127.0.0.1', port=50051):
    server = grpc.aio.server()
    helloworld_pb2_grpc.add_GreeterServicer_to_server(Greeter(), server)
    server.add_insecure_port(f'{host}:{port}')
    await server.start()
    print(f'Serving on {host}:{port}')
    try:
        await server.wait_for_termination()
    finally:
        await server.stop(10)


if __name__ == '__main__':
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass
