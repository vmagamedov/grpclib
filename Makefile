proto:
	python -m grpc_tools.protoc -I./example --python_out=./example --grpc_python_out=./example --python-grpc_out=./example ./example/helloworld.proto
	python -m grpc_tools.protoc -I./tests --python_out=./tests --python-grpc_out=./tests ./tests/protobuf/testing.proto

server:
	@PYTHONPATH=. python example/server.py

client:
	@PYTHONPATH=. python example/client.py
