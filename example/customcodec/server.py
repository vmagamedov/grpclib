import asyncio
from grpclib.server import Server
import grpclib
from .codec import JSONCodec


class Greeter:

    async def unary_unary_greeting(self, stream):
        msg = await stream.recv_message()
        await stream.send_message({'greeting': 'hello, %s' % msg['name']})

    def __mapping__(self):
        return {
            '/HelloWorld/UnaryUnaryGreeting': grpclib.const.Handler(
                self.unary_unary_greeting,
                grpclib.const.Cardinality.UNARY_UNARY,
                None,
                None
            )
        }


def main():
    loop = asyncio.get_event_loop()

    server = Server([Greeter()], loop=loop, codec=JSONCodec)
    host, port = '127.0.0.1', 50051
    loop.run_until_complete(server.start(host, port))

    print('Serving on {}:{}'.format(host, port))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    server.close()
    loop.run_until_complete(server.wait_closed())
    loop.close()


if __name__ == '__main__':
    main()
