import time

import grpc

from helloworld import helloworld_pb2
from helloworld import helloworld_pb2_grpc


def main(iterations: int = 10, count: int = 1000) -> None:
    channel = grpc.insecure_channel('127.0.0.1:50051')
    stub = helloworld_pb2_grpc.GreeterStub(channel)

    for _ in range(iterations):
        t1 = time.time()
        for _ in range(count):
            stub.SayHello(helloworld_pb2.HelloRequest(name='World'))
        t2 = time.time()
        secs = (t2 - t1)
        rps = int(count / (t2 - t1))
        print('{} requests in {:.2f} secs ~= {} rps'.format(count, secs, rps))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
