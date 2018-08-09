__default__:
	@echo "Please specify a target to make"

clean:
	rm -f ./grpclib/reflection/v1alpha/*_pb2.py
	rm -f ./grpclib/reflection/v1alpha/*_grpc.py
	rm -f ./example/helloworld/*_pb2.py
	rm -f ./example/helloworld/*_grpc.py
	rm -f ./tests/*_pb2.py
	rm -f ./tests/*_grpc.py

proto: clean
	python3 -m grpc_tools.protoc -I. --python_out=. --python_grpc_out=. grpclib/reflection/v1alpha/reflection.proto
	cd example; python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. --python_grpc_out=. helloworld/helloworld.proto
	cd tests; python3 -m grpc_tools.protoc -I. --python_out=. --python_grpc_out=. dummy.proto

release: proto
	./scripts/release_check.sh
	rm -rf grpclib.egg-info
	python setup.py sdist

server:
	@PYTHONPATH=example python3 -m helloworld.server

_server:
	@PYTHONPATH=example python3 -m helloworld._reference.server

client:
	@PYTHONPATH=example python3 -m helloworld.client

_client:
	@PYTHONPATH=example python3 -m helloworld._reference.client
