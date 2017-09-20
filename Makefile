proto: clean
	cd example; python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. --python_grpc_out=. greeter/helloworld.proto
	cd tests; python3 -m grpc_tools.protoc -I. --python_out=. --python_grpc_out=. bombed.proto

server:
	@PYTHONPATH=. cd example; python3 -m greeter.server

_server:
	@PYTHONPATH=. cd example; python3 -m greeter._reference.server

client:
	@PYTHONPATH=. cd example; python3 -m greeter.client

_client:
	@PYTHONPATH=. cd example; python3 -m greeter._reference.client

clean:
	rm -f ./example/greeter/*_pb2.py
	rm -f ./example/greeter/*_grpc.py
	rm -f ./tests/*_pb2.py
	rm -f ./tests/*_grpc.py
