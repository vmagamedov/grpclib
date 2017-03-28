import struct
import asyncio
import weakref

import aioh2

from multidict import MultiDict

from helloworld_pb2 import HelloRequest, HelloReply


class H2Protocol(aioh2.H2Protocol):
    _handler_task = None

    def __init__(self, handler, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._handler = handler

    def connection_made(self, transport):
        super().connection_made(transport)
        self._handler_task = self._loop.create_task(
            self._handler(self, loop=self._loop)
        )

    def connection_lost(self, exc):
        super().connection_lost(exc)
        self._handler_task.cancel()

    async def shutdown(self):
        if self._handler_task.cancel():
            try:
                await self._handler_task
            except asyncio.CancelledError:
                pass


async def say_hello(request):
    await asyncio.sleep(10)
    return HelloReply(message='Hello, {}!'.format(request.name))


async def unary_unary(proto, stream_id, behavior, request_type, reply_type):
    # print(request_type, reply_type)

    request_data = await proto.read_stream(stream_id, -1)
    # print('request_bin', request_data)

    compressed_flag = struct.unpack('?', request_data[0:1])[0]
    if compressed_flag:
        raise NotImplementedError('Compression not implemented')

    request_len = struct.unpack('>I', request_data[1:5])[0]
    request_bin = request_data[5:]
    assert len(request_bin) == request_len, \
        '{} != {}'.format(len(request_bin), request_len)

    request_msg = request_type.FromString(request_bin)

    reply_msg = await behavior(request_msg)
    assert isinstance(reply_msg, reply_type), type(reply_msg)

    reply_bin = reply_msg.SerializeToString()

    reply_data = (struct.pack('?', False)
                  + struct.pack('>I', len(reply_bin))
                  + reply_bin)
    await proto.send_data(stream_id, reply_data)


async def request_handler(proto, stream_id, headers):
    # print(stream_id, headers)

    h2_method = headers[':method']
    assert h2_method == 'POST', h2_method

    h2_path = headers[':path']
    assert h2_path == '/helloworld.Greeter/SayHello', h2_path

    await proto.send_headers(stream_id,
                             {':status': '200',
                              'content-type': 'application/grpc+proto'})

    await unary_unary(proto, stream_id, say_hello,
                      HelloRequest, HelloReply)

    await proto.send_headers(stream_id,
                             {'grpc-status': '0'},
                             end_stream=True)


async def connection_handler(proto, *, loop):
    tasks = {}
    try:
        while True:
            stream_id, headers = await proto.recv_request()
            tasks[stream_id] = loop.create_task(
                request_handler(proto, stream_id, MultiDict(headers))
            )
    except asyncio.CancelledError:
        for task in tasks.values():
            task.cancel()


async def create_server(*, loop):
    protocols = weakref.WeakSet()

    def protocol_factory():
        proto = H2Protocol(connection_handler, False, loop=loop)
        protocols.add(proto)
        return proto

    server = await loop.create_server(protocol_factory, 'localhost', 50051)

    async def close():
        for proto in protocols:
            await proto.shutdown()
        server.close()
        await server.wait_closed()

    return close


def main():
    loop = asyncio.get_event_loop()
    close = loop.run_until_complete(create_server(loop=loop))
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    loop.run_until_complete(close())
    loop.close()


if __name__ == '__main__':
    main()
