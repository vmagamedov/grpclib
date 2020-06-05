import sys; sys.path.append('examples')  # noqa

import struct
import asyncio
import tempfile
import subprocess

import click

from grpclib.utils import graceful_exit
from grpclib.server import Server
from grpclib.encoding.proto import ProtoCodec

from helloworld.server import Greeter
from helloworld.helloworld_pb2 import HelloRequest, HelloReply


REQUEST = HelloRequest(name='Dr. Strange')


def grpc_encode(message, message_type, codec=ProtoCodec()):
    message_bin = codec.encode(message, message_type)
    header = struct.pack('?', False) + struct.pack('>I', len(message_bin))
    return header + message_bin


@click.group()
def cli():
    pass


@cli.group()
def serve():
    pass


@cli.group()
def bench():
    pass


async def _grpclib_server(*, host='127.0.0.1', port=50051):
    server = Server([Greeter()])
    with graceful_exit([server]):
        await server.start(host, port)
        print(f'Serving on {host}:{port}')
        await server.wait_closed()


@serve.command('grpclib')
def serve_grpclib():
    asyncio.run(_grpclib_server())


@serve.command('grpclib+uvloop')
def serve_grpclib_uvloop():
    import uvloop
    uvloop.install()

    asyncio.run(_grpclib_server())


@serve.command('grpcio')
def serve_grpcio():
    from _reference.server import serve

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


@serve.command('grpcio+uvloop')
def serve_grpcio_uvloop():
    import uvloop
    uvloop.install()

    from _reference.server import serve

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        pass


def _aiohttp_server(*, host='127.0.0.1', port=8000):
    from aiohttp import web

    async def handle(request):
        hello_request = HelloRequest.FromString(await request.read())
        hello_reply = HelloReply(message=f'Hello, {hello_request.name}!')
        return web.Response(body=hello_reply.SerializeToString())

    app = web.Application()
    app.add_routes([web.post('/', handle)])
    web.run_app(app, host=host, port=port, access_log=None)


@serve.command('aiohttp')
def serve_aiohttp():
    _aiohttp_server()


@serve.command('aiohttp+uvloop')
def serve_aiohttp_uvloop():
    import uvloop
    uvloop.install()

    _aiohttp_server()


@bench.command('grpc')
@click.option('-n', type=int, default=1000)
@click.option('--seq', is_flag=True)
def bench_grpc(n, seq):
    connections = 1 if seq else 10
    streams = 1 if seq else 10
    with tempfile.NamedTemporaryFile() as f:
        f.write(grpc_encode(REQUEST, HelloRequest))
        f.flush()
        subprocess.run([
            'h2load', 'http://localhost:50051/helloworld.Greeter/SayHello',
            '-d', f.name,
            '-H', 'te: trailers',
            '-H', 'content-type: application/grpc+proto',
            '-n', str(n),
            '-c', str(connections),
            '-m', str(streams),
        ])


@bench.command('http')
@click.option('-n', type=int, default=1000)
@click.option('--seq', is_flag=True)
def bench_http(n, seq):
    connections = 1 if seq else 10
    with tempfile.NamedTemporaryFile() as f:
        f.write(REQUEST.SerializeToString())
        f.flush()
        subprocess.run([
            'h2load', 'http://localhost:8000/',
            '--h1',
            '-d', f.name,
            '-H', 'content-type: application/protobuf',
            '-n', str(n),
            '-c', str(connections),
        ])


if __name__ == '__main__':
    cli()
