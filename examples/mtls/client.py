import os
import ssl
import asyncio
import logging

from pathlib import Path

from grpclib.client import Channel
from grpclib.health.v1.health_pb2 import HealthCheckRequest
from grpclib.health.v1.health_grpclib import HealthStub


DIR = Path(__file__).parent.joinpath('keys')
SPY_MODE = 'SPY_MODE' in os.environ

SERVER_CERT = DIR.joinpath('mccoy.pem')
CLIENT_CERT = DIR.joinpath('spock-imposter.pem' if SPY_MODE else 'spock.pem')
CLIENT_KEY = DIR.joinpath('spock-imposter.key' if SPY_MODE else 'spock.key')


def create_secure_context(
    client_cert: Path, client_key: Path, *, trusted: Path,
) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS)
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_cert_chain(str(client_cert), str(client_key))
    ctx.load_verify_locations(str(trusted))
    ctx.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1
    ctx.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:DHE+CHACHA20')
    ctx.set_alpn_protocols(['h2'])
    try:
        ctx.set_npn_protocols(['h2'])
    except NotImplementedError:
        pass
    return ctx


async def main(*, host: str = 'localhost', port: int = 50051) -> None:
    channel = Channel(host, port, ssl=create_secure_context(
        CLIENT_CERT, CLIENT_KEY, trusted=SERVER_CERT,
    ))
    stub = HealthStub(channel)
    response = await stub.Check(HealthCheckRequest())
    print(response)
    channel.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
