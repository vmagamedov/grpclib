import time

import grpc

from helloworld import helloworld_pb2
from helloworld import helloworld_pb2_grpc


def main(iterations=10, count=1000):
    channel = grpc.insecure_channel('127.0.0.1:50051')
    stub = helloworld_pb2_grpc.GreeterStub(channel)

    for j in range(iterations):
        t1 = time.time()
        for i in range(count):
            stub.SayHello(helloworld_pb2.HelloRequest(name='World'))
        t2 = time.time()
        secs = (t2 - t1)
        rps = int(count / (t2 - t1))
        print(f'{count} requests in {secs:.2f} secs ~= {rps} rps')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
