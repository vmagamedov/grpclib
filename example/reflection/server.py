import asyncio

from grpclib.server import Server
from grpclib.reflection.service import ServerReflection

from helloworld.server import Greeter, run


def main():
    loop = asyncio.get_event_loop()

    services = [Greeter()]
    services = ServerReflection.extend(services)

    server = Server(services, loop=loop)
    run(server, loop=loop)


if __name__ == '__main__':
    main()
