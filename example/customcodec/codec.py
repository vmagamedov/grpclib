import json
import struct


class JSONCodec:

    CONTENT_TYPE = 'application/grpc+json'
    CONTENT_TYPES = {'application/grpc', 'application/grpc+json'}

    @staticmethod
    async def recv_message(stream, message_type):
        header = await stream.recv_data(4)
        if not header:
            return

        message_len = struct.unpack('I', header)[0]
        message_bin = await stream.recv_data(message_len)
        
        return json.loads(message_bin)

    @staticmethod
    async def send_message(stream, message, message_type, *, end=False):
        message_bin = json.dumps(message).encode('utf-8')

        await stream.send_data(
            struct.pack('I', len(message_bin)) + message_bin, 
            end_stream=end)
