proto: clean
	protoc -I./example --python_out=./example --python_grpc_out=./example ./example/helloworld.proto
	protoc -I./tests --python_out=./tests --python_grpc_out=./tests ./tests/protobuf/testing.proto

server:
	@PYTHONPATH=. python example/server.py

client:
	@PYTHONPATH=. python example/client.py

clean:
	rm -f ./example/*_pb2*
	rm -f ./tests/protobuf/*_pb2*
