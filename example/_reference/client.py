import time

import grpc

from .. import helloworld_pb2
from .. import helloworld_pb2_grpc


def main1():
    channel = grpc.insecure_channel('127.0.0.1:50051')
    stub = helloworld_pb2_grpc.GreeterStub(channel)

    print(stub.SayHello(helloworld_pb2.HelloRequest(name='World')))


def main2():
    channel = grpc.insecure_channel('127.0.0.1:50051')
    stub = helloworld_pb2_grpc.GreeterStub(channel)

    t1 = time.time()
    for i in range(1000):
        stub.SayHello(helloworld_pb2.HelloRequest(name='World'))
    t2 = time.time()
    print('{} rps'.format(int(1000 / (t2 - t1))))


if __name__ == '__main__':
    main1()
