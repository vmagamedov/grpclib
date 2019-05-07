import asyncio

from grpclib.utils import graceful_exit
from grpclib.server import Server
from grpclib.reflection.service import ServerReflection

from helloworld.server import Greeter


async def main(*, host='127.0.0.1', port=50051):
    services = [Greeter()]
    services = ServerReflection.extend(services)

    server = Server(services)
    with graceful_exit([server]):
        await server.start(host, port)
        print(f'Serving on {host}:{port}')
        await server.wait_closed()


if __name__ == '__main__':
    asyncio.run(main())
