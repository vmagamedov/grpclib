proto: clean
	python3 -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. --python_grpc_out=. example/helloworld.proto
	python3 -m grpc_tools.protoc -Itests --python_out=tests --python_grpc_out=tests tests/protobuf/testing.proto

server:
	@PYTHONPATH=. python example/server.py

client:
	@PYTHONPATH=. python example/client.py

clean:
	rm -f ./example/*_pb2.py
	rm -f ./example/*_grpc.py
	rm -f ./tests/protobuf/*_pb2.py
	rm -f ./tests/protobuf/*_grpc.py
