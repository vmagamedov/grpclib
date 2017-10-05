proto: clean
	cd example; python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. --python_grpc_out=. helloworld/helloworld.proto
	cd tests; python3 -m grpc_tools.protoc -I. --python_out=. --python_grpc_out=. bombed.proto

server:
	@PYTHONPATH=. cd example; python3 -m helloworld.server

_server:
	@PYTHONPATH=. cd example; python3 -m helloworld._reference.server

client:
	@PYTHONPATH=. cd example; python3 -m helloworld.client

_client:
	@PYTHONPATH=. cd example; python3 -m helloworld._reference.client

clean:
	rm -f ./example/helloworld/*_pb2.py
	rm -f ./example/helloworld/*_grpc.py
	rm -f ./tests/*_pb2.py
	rm -f ./tests/*_grpc.py
