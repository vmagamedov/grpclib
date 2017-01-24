import sys

import grpc

from helloworld_pb2 import HelloRequest
from helloworld_pb2_grpc import GreeterStub


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else 'World'

    channel = grpc.insecure_channel('localhost:50051')
    stub = GreeterStub(channel)

    hello_reply = stub.SayHello(HelloRequest(name=name))
    print(hello_reply)


if __name__ == '__main__':
    main()
