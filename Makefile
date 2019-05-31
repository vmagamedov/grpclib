__default__:
	@echo "Please specify a target to make"

clean:
	rm -f ./grpclib/health/v1/*_pb2.py
	rm -f ./grpclib/health/v1/*_grpc.py
	rm -f ./grpclib/health/v1/*.pyi
	rm -f ./grpclib/reflection/v1/*_pb2.py
	rm -f ./grpclib/reflection/v1/*_grpc.py
	rm -f ./grpclib/reflection/v1/*.pyi
	rm -f ./examples/helloworld/*_pb2.py
	rm -f ./examples/helloworld/*_grpc.py
	rm -f ./examples/helloworld/*.pyi
	rm -f ./examples/streaming/*_pb2.py
	rm -f ./examples/streaming/*_grpc.py
	rm -f ./examples/streaming/*.pyi
	rm -f ./examples/multiproc/*_pb2.py
	rm -f ./examples/multiproc/*_grpc.py
	rm -f ./examples/multiproc/*.pyi
	rm -f ./tests/*_pb2.py
	rm -f ./tests/*_grpc.py
	rm -f ./tests/*.pyi

proto: clean
	python3 -m grpc_tools.protoc -I. --python_out=. --python_grpc_out=. --mypy_out=. grpclib/health/v1/health.proto
	python3 -m grpc_tools.protoc -I. --python_out=. --python_grpc_out=. --mypy_out=. grpclib/reflection/v1/reflection.proto
	python3 -m grpc_tools.protoc -Iexamples --python_out=examples --python_grpc_out=examples --grpc_python_out=examples --mypy_out=examples examples/helloworld/helloworld.proto
	python3 -m grpc_tools.protoc -Iexamples --python_out=examples --python_grpc_out=examples --mypy_out=examples examples/streaming/helloworld.proto
	python3 -m grpc_tools.protoc -Iexamples --python_out=examples --python_grpc_out=examples --mypy_out=examples examples/multiproc/primes.proto
	cd tests; python3 -m grpc_tools.protoc -I. --python_out=. --python_grpc_out=. --mypy_out=. dummy.proto

release: proto
	./scripts/release_check.sh
	rm -rf grpclib.egg-info
	python setup.py sdist

server:
	@PYTHONPATH=examples python3 -m reflection.server

server_streaming:
	@PYTHONPATH=examples python3 -m streaming.server

_server:
	@PYTHONPATH=examples python3 -m _reference.server

client:
	@PYTHONPATH=examples python3 -m helloworld.client

client_streaming:
	@PYTHONPATH=examples python3 -m streaming.client

_client:
	@PYTHONPATH=examples python3 -m _reference.client
