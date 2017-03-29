stubs:
	python -m grpc_tools.protoc -I./example --python_out=./example --grpc_python_out=./example --python_asyncgrpc_out=./example ./example/helloworld.proto

server:
	@PYTHONPATH=. python example/server.py

client:
	@python example/client.py
