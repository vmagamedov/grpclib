import asyncio

from grpclib.server import Server
from grpclib.reflection.service import ServerReflection

from helloworld.server import Greeter, serve


async def main():
    services = [Greeter()]
    services = ServerReflection.extend(services)

    server = Server(services, loop=asyncio.get_event_loop())
    await serve(server)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
