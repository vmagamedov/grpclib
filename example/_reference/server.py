import time
import concurrent.futures

import grpc

from helloworld import helloworld_pb2
from helloworld import helloworld_pb2_grpc


class Greeter(helloworld_pb2_grpc.GreeterServicer):

    def SayHello(self, request, context):
        return helloworld_pb2.HelloReply(message='Hello, %s!' % request.name)


def serve(host='127.0.0.1', port=50051):
    server = grpc.server(concurrent.futures.ThreadPoolExecutor(max_workers=10))
    helloworld_pb2_grpc.add_GreeterServicer_to_server(Greeter(), server)
    server.add_insecure_port(f'{host}:{port}')
    server.start()
    print(f'Serving on {host}:{port}')
    try:
        while True:
            time.sleep(3600)
    finally:
        server.stop(0)


if __name__ == '__main__':
    try:
        serve()
    except KeyboardInterrupt:
        pass
