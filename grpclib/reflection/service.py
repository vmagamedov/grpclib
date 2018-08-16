# This code is heavily based on grpcio-reflection reference implementation:
#
#     Copyright 2016 gRPC authors.
#
#     Licensed under the Apache License, Version 2.0 (the "License");
#     you may not use this file except in compliance with the License.
#     You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.
#
from google.protobuf import descriptor_pool
from google.protobuf.descriptor_pb2 import FileDescriptorProto

from ..const import Status
from ..utils import _service_name

from .v1 import reflection_pb2
from .v1.reflection_grpc import ServerReflectionBase

from .v1alpha import reflection_pb2 as reflection_pb2_v1alpha
from .v1alpha.reflection_grpc import (
    ServerReflectionBase as ServerReflectionBaseV1Alpha
)


class _ServerReflection:

    def __init__(self, pb, service_names):
        self._pb = pb
        self._service_names = service_names
        self._pool = descriptor_pool.Default()

    def _not_found_response(self):
        return self._pb.ServerReflectionResponse(
            error_response=self._pb.ErrorResponse(
                error_code=Status.NOT_FOUND.value,
                error_message='not found',
            ),
        )

    def _file_descriptor_response(self, file_descriptor):
        proto = FileDescriptorProto()
        file_descriptor.CopyToProto(proto)
        return self._pb.ServerReflectionResponse(
            file_descriptor_response=self._pb.FileDescriptorResponse(
                file_descriptor_proto=[proto.SerializeToString()],
            ),
        )

    def _file_by_filename_response(self, file_name):
        try:
            file = self._pool.FindFileByName(file_name)
        except KeyError:
            return self._not_found_response()
        else:
            return self._file_descriptor_response(file)

    def _file_containing_symbol_response(self, symbol):
        try:
            file = self._pool.FindFileContainingSymbol(symbol)
        except KeyError:
            return self._not_found_response()
        else:
            return self._file_descriptor_response(file)

    def _file_containing_extension_response(self, msg_name, ext_number):
        try:
            message = self._pool.FindMessageTypeByName(msg_name)
            extension = self._pool.FindExtensionByNumber(message, ext_number)
            file = self._pool.FindFileContainingSymbol(extension.full_name)
        except KeyError:
            return self._not_found_response()
        else:
            return self._file_descriptor_response(file)

    def _all_extension_numbers_of_type_response(self, type_name):
        try:
            message = self._pool.FindMessageTypeByName(type_name)
            extensions = self._pool.FindAllExtensions(message)
        except KeyError:
            return self._not_found_response()
        else:
            return self._pb.ServerReflectionResponse(
                all_extension_numbers_response=self._pb.ExtensionNumberResponse(
                    base_type_name=message.full_name,
                    extension_number=[ext.number for ext in extensions],
                )
            )

    def _list_services_response(self):
        return self._pb.ServerReflectionResponse(
            list_services_response=self._pb.ListServiceResponse(
                service=[self._pb.ServiceResponse(name=service_name)
                         for service_name in self._service_names],
            )
        )

    async def ServerReflectionInfo(self, stream):
        async for request in stream:
            if request.HasField('file_by_filename'):
                response = self._file_by_filename_response(
                    request.file_by_filename,
                )
            elif request.HasField('file_containing_symbol'):
                response = self._file_containing_symbol_response(
                    request.file_containing_symbol,
                )
            elif request.HasField('file_containing_extension'):
                response = self._file_containing_extension_response(
                    request.file_containing_extension.containing_type,
                    request.file_containing_extension.extension_number,
                )
            elif request.HasField('all_extension_numbers_of_type'):
                response = self._all_extension_numbers_of_type_response(
                    request.all_extension_numbers_of_type,
                )
            elif request.HasField('list_services'):
                response = self._list_services_response()
            else:
                response = self._pb.ServerReflectionResponse(
                    error_response=self._pb.ErrorResponse(
                        error_code=Status.INVALID_ARGUMENT.value,
                        error_message='invalid argument',
                    )
                )
            await stream.send_message(response)


class ServerReflectionV1Alpha(_ServerReflection, ServerReflectionBaseV1Alpha):
    pass


class ServerReflection(_ServerReflection, ServerReflectionBase):
    """
    Implements server reflection protocol.
    """
    @classmethod
    def extend(cls, services):
        """
        Extends services list with reflection service:

        .. code-block:: python

            from grpclib.reflection.service import ServerReflection

            services = [Greeter()]
            services = ServerReflection.extend(services)

            server = Server(services, loop=loop)
            ...

        Returns new services list with reflection support added.
        """
        service_names = []
        for service in services:
            service_names.append(_service_name(service))
        services = list(services)
        services.append(cls(reflection_pb2, service_names))
        services.append(ServerReflectionV1Alpha(reflection_pb2_v1alpha,
                                                service_names))
        return services
