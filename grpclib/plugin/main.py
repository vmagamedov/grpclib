import os
import sys

from contextlib import contextmanager
from collections import namedtuple

from google.protobuf.compiler.plugin_pb2 import CodeGeneratorRequest
from google.protobuf.compiler.plugin_pb2 import CodeGeneratorResponse

from grpclib import const
from grpclib import client


SUFFIX = '_grpc.py'

_CARDINALITY = {
    (False, False): const.Cardinality.UNARY_UNARY,
    (True, False): const.Cardinality.STREAM_UNARY,
    (False, True): const.Cardinality.UNARY_STREAM,
    (True, True): const.Cardinality.STREAM_STREAM,
}


class Buffer:

    def __init__(self):
        self._lines = []
        self._indent = 0

    def add(self, string, *args, **kwargs):
        line = ' ' * self._indent * 4 + string.format(*args, **kwargs)
        self._lines.append(line.rstrip(' '))

    @contextmanager
    def indent(self):
        self._indent += 1
        try:
            yield
        finally:
            self._indent -= 1

    def content(self):
        return '\n'.join(self._lines) + '\n'


def render(proto_file, package, imports, services):
    buf = Buffer()
    buf.add('# Generated by the Protocol Buffers compiler. DO NOT EDIT!')
    buf.add('# source: {}', proto_file)
    buf.add('# plugin: {}', __name__)
    if not services:
        return buf.content()

    buf.add('import abc')
    buf.add('')
    buf.add('import {}', const.__name__)
    buf.add('import {}', client.__name__)
    buf.add('')
    for mod in imports:
        buf.add('import {}', mod)
    for service in services:
        if package:
            service_name = '{}.{}'.format(package, service.name)
        else:
            service_name = service.name
        buf.add('')
        buf.add('')
        buf.add('class {}Base(abc.ABC):', service.name)
        with buf.indent():
            for (name, _, _, _) in service.methods:
                buf.add('')
                buf.add('@abc.abstractmethod')
                buf.add('async def {}(self, stream):', name)
                with buf.indent():
                    buf.add('pass')
            buf.add('')
            buf.add('def __mapping__(self):')
            with buf.indent():
                buf.add('return {{')
                with buf.indent():
                    for method in service.methods:
                        name, cardinality, request_type, reply_type = method
                        full_name = '/{}/{}'.format(service_name, name)
                        buf.add("'{}': {}.{}(", full_name, const.__name__,
                                const.Handler.__name__)
                        with buf.indent():
                            buf.add('self.{},', name)
                            buf.add('{}.{}.{},', const.__name__,
                                    const.Cardinality.__name__,
                                    cardinality.name)
                            buf.add('{},', request_type)
                            buf.add('{},', reply_type)
                        buf.add('),')
                buf.add('}}')

        buf.add('')
        buf.add('')
        buf.add('class {}Stub:', service.name)
        with buf.indent():
            buf.add('')
            buf.add('def __init__(self, channel: {}.{}) -> None:'
                    .format(client.__name__, client.Channel.__name__))
            with buf.indent():
                for method in service.methods:
                    name, cardinality, request_type, reply_type = method
                    full_name = '/{}/{}'.format(service_name, name)
                    if cardinality is const.Cardinality.UNARY_UNARY:
                        method_cls = client.UnaryUnaryMethod
                    elif cardinality is const.Cardinality.UNARY_STREAM:
                        method_cls = client.UnaryStreamMethod
                    elif cardinality is const.Cardinality.STREAM_UNARY:
                        method_cls = client.StreamUnaryMethod
                    elif cardinality is const.Cardinality.STREAM_STREAM:
                        method_cls = client.StreamStreamMethod
                    else:
                        raise TypeError(cardinality)
                    buf.add('self.{} = {}.{}('.format(name, client.__name__,
                                                      method_cls.__name__))
                    with buf.indent():
                        buf.add('channel,')
                        buf.add('{!r},'.format(full_name))
                        buf.add('{},', request_type)
                        buf.add('{},', reply_type)
                    buf.add(')')
    return buf.content()


Service = namedtuple('Service', 'name methods')


def _get_proto(request, name):
    return next(f for f in request.proto_file if f.name == name)


def _proto2py(proto_name):
    return proto_name.replace('/', '.')[:-len('.proto')] + '_pb2'


def _type_name(proto_file, message_type):
    if proto_file.package:
        return '.{}.{}'.format(proto_file.package, message_type.name)
    else:
        return '.{}'.format(message_type.name)


def main():
    with os.fdopen(sys.stdin.fileno(), 'rb') as inp:
        request = CodeGeneratorRequest.FromString(inp.read())

    types_map = {
        _type_name(pf, mt): '.'.join((_proto2py(pf.name), mt.name))
        for pf in request.proto_file
        for mt in pf.message_type
    }

    response = CodeGeneratorResponse()
    for file_to_generate in request.file_to_generate:
        proto_file = _get_proto(request, file_to_generate)

        imports = [_proto2py(dep)
                   for dep in list(proto_file.dependency) + [file_to_generate]]

        services = []
        for service in proto_file.service:
            methods = []
            for method in service.method:
                cardinality = _CARDINALITY[(method.client_streaming,
                                            method.server_streaming)]
                methods.append((
                    method.name,
                    cardinality,
                    types_map[method.input_type],
                    types_map[method.output_type],
                ))
            services.append(Service(service.name,
                                    methods=methods))

        out = response.file.add()
        out.name = file_to_generate.replace('.proto', SUFFIX)
        out.content = render(proto_file=proto_file.name,
                             package=proto_file.package,
                             imports=imports,
                             services=services)

    with os.fdopen(sys.stdout.fileno(), 'wb') as out:
        out.write(response.SerializeToString())


if __name__ == '__main__':
    main()
