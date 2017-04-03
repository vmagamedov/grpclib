proto:
	python -m grpc_tools.protoc -I./example --python_out=./example --grpc_python_out=./example --python-grpc_out=./example ./example/helloworld.proto

server:
	@PYTHONPATH=. python example/server.py

client:
	@PYTHONPATH=. python example/client.py
