import os
import ssl
import asyncio
import logging

from pathlib import Path

from grpclib.utils import graceful_exit
from grpclib.server import Server
from grpclib.health.service import Health


DIR = Path(__file__).parent.joinpath('keys')
SPY_MODE = 'SPY_MODE' in os.environ

CLIENT_CERT = DIR.joinpath('spock.pem')
SERVER_CERT = DIR.joinpath('mccoy-imposter.pem' if SPY_MODE else 'mccoy.pem')
SERVER_KEY = DIR.joinpath('mccoy-imposter.key' if SPY_MODE else 'mccoy.key')


def create_secure_context(
    server_cert: Path, server_key: Path, *, trusted: Path,
) -> ssl.SSLContext:
    ctx = ssl.create_default_context(
        ssl.Purpose.CLIENT_AUTH,
        cafile=str(trusted),
    )
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_cert_chain(str(server_cert), str(server_key))
    ctx.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20')
    ctx.set_alpn_protocols(['h2'])
    return ctx


async def main(*, host: str = '0.0.0.0', port: int = 50051) -> None:
    server = Server([Health()])
    with graceful_exit([server]):
        await server.start(host, port, ssl=create_secure_context(
            SERVER_CERT, SERVER_KEY, trusted=CLIENT_CERT,
        ))
        print(f'Serving on {host}:{port}')
        await server.wait_closed()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
