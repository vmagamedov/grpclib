import grpc

from helloworld import helloworld_pb2
from helloworld import helloworld_pb2_grpc


def main() -> None:
    channel = grpc.insecure_channel('127.0.0.1:50051')
    stub = helloworld_pb2_grpc.GreeterStub(channel)

    print(stub.SayHello(helloworld_pb2.HelloRequest(name='World')))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        pass
