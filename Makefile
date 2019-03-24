__default__:
	@echo "Please specify a target to make"

clean:
	rm -f ./grpclib/health/v1/*_pb2.py
	rm -f ./grpclib/health/v1/*_grpc.py
	rm -f ./grpclib/reflection/v1/*_pb2.py
	rm -f ./grpclib/reflection/v1/*_grpc.py
	rm -f ./grpclib/reflection/v1alpha/*_pb2.py
	rm -f ./grpclib/reflection/v1alpha/*_grpc.py
	rm -f ./example/helloworld/*_pb2.py
	rm -f ./example/helloworld/*_grpc.py
	rm -f ./example/streaming/*_pb2.py
	rm -f ./example/streaming/*_grpc.py
	rm -f ./tests/*_pb2.py
	rm -f ./tests/*_grpc.py

proto: clean
	python3 -m grpc_tools.protoc -I. --python_out=. --mypy_out=. --python_grpc_out=. grpclib/health/v1/health.proto
	python3 -m grpc_tools.protoc -I. --python_out=. --mypy_out=. --python_grpc_out=. grpclib/reflection/v1/reflection.proto
	python3 -m grpc_tools.protoc -I. --python_out=. --mypy_out=. --python_grpc_out=. grpclib/reflection/v1alpha/reflection.proto
	python3 -m grpc_tools.protoc -Iexample --python_out=example --mypy_out=example --python_grpc_out=example --grpc_python_out=example example/helloworld/helloworld.proto
	python3 -m grpc_tools.protoc -Iexample --python_out=example --mypy_out=example --python_grpc_out=example example/streaming/helloworld.proto
	cd tests; python3 -m grpc_tools.protoc -I. --python_out=. --mypy_out=. --python_grpc_out=. dummy.proto

release: proto
	./scripts/release_check.sh
	rm -rf grpclib.egg-info
	python setup.py sdist

server:
	@PYTHONPATH=example python3 -m reflection.server

server_streaming:
	@PYTHONPATH=example python3 -m streaming.server

_server:
	@PYTHONPATH=example python3 -m _reference.server

client:
	@PYTHONPATH=example python3 -m helloworld.client

client_streaming:
	@PYTHONPATH=example python3 -m streaming.client

_client:
	@PYTHONPATH=example python3 -m _reference.client

_bench:
	@PYTHONPATH=example python3 -m _reference.bench
