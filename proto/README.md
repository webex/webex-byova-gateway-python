# Protocol Buffer Definitions

This directory contains Protocol Buffer (protobuf) definitions for the Webex Contact Center BYOVA Gateway.

## Purpose

Protobuf files define the data structures and service interfaces used for:
- gRPC communication with Webex Contact Center
- Internal service communication
- Data serialization and deserialization

## File Structure

- Service definitions (`.proto` files)
- Generated Python code (if using `grpcio-tools`)
- Documentation for each service interface

## Usage

1. Define service interfaces in `.proto` files
2. Generate Python code using `grpcio-tools`
3. Import generated classes in your Python code

## Example

```bash
# Generate Python code from proto files
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. service.proto
``` 