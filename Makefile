proto: clean
	python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. --python_grpc_out=. example/helloworld.proto
	python3 -m grpc_tools.protoc -I. --python_out=. --python_grpc_out=. tests/protobuf/testing.proto

server:
	@PYTHONPATH=. python -m example.server

_server:
	@PYTHONPATH=. python -m example._reference.server

client:
	@PYTHONPATH=. python -m example.client

_client:
	@PYTHONPATH=. python -m example._reference.client

clean:
	rm -f ./example/*_pb2.py
	rm -f ./example/*_grpc.py
	rm -f ./tests/protobuf/*_pb2.py
	rm -f ./tests/protobuf/*_grpc.py
