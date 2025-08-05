# Protocol Buffer Definitions

This directory contains Protocol Buffer (protobuf) definitions for the Webex Contact Center BYOVA Gateway, defining the data structures and service interfaces used for gRPC communication.

## Purpose

Protobuf files serve as the contract between the gateway and Webex Contact Center:

- **Service Definitions**: Define gRPC service interfaces and methods
- **Data Structures**: Specify message formats for requests and responses
- **Type Safety**: Ensure type-safe communication between services
- **Versioning**: Support for API versioning and backward compatibility
- **Documentation**: Self-documenting API specifications

## File Structure

### Core Protocol Files

- **`byova_common.proto`**: Common data structures and shared types
- **`voicevirtualagent.proto`**: Voice virtual agent service definitions

### Generated Files

When using `grpcio-tools`, the following Python files are generated:

- **`byova_common_pb2.py`**: Python classes for common data structures
- **`byova_common_pb2_grpc.py`**: gRPC service definitions for common services
- **`voicevirtualagent_pb2.py`**: Python classes for voice virtual agent data
- **`voicevirtualagent_pb2_grpc.py`**: gRPC service definitions for voice virtual agent

## Service Definitions

### Voice Virtual Agent Service

The main service interface for virtual agent communication:

```protobuf
service VoiceVirtualAgent {
  // List available virtual agents
  rpc ListVirtualAgents(ListVirtualAgentsRequest) 
      returns (ListVirtualAgentsResponse);
  
  // Process caller input via bidirectional streaming
  rpc ProcessCallerInput(stream VoiceVARequest) 
      returns (stream VoiceVAResponse);
}
```

### Key Message Types

#### VoiceVARequest
```protobuf
message VoiceVARequest {
  string conversation_id = 1;
  string virtual_agent_id = 2;
  string customer_org_id = 3;
  bytes audio_content = 4;
  string text_content = 5;
  RequestType request_type = 6;
}
```

#### VoiceVAResponse
```protobuf
message VoiceVAResponse {
  string conversation_id = 1;
  bytes audio_content = 2;
  string text_content = 3;
  ResponseType response_type = 4;
  bool is_barge_in_enabled = 5;
  SessionStatus session_status = 6;
}
```

## Usage

### 1. Define Service Interfaces

Create or modify `.proto` files to define your service interfaces:

```protobuf
syntax = "proto3";

package byova;

// Import common definitions
import "byova_common.proto";

// Define your service
service MyService {
  rpc MyMethod(MyRequest) returns (MyResponse);
}

// Define message types
message MyRequest {
  string id = 1;
  bytes data = 2;
}

message MyResponse {
  string result = 1;
  int32 status = 2;
}
```

### 2. Generate Python Code

Use `grpcio-tools` to generate Python code from proto files:

```bash
# Generate Python code from proto files
python -m grpc_tools.protoc \
  -Iproto \
  --python_out=src/core \
  --grpc_python_out=src/core \
  proto/byova_common.proto \
  proto/voicevirtualagent.proto
```

### 3. Use Generated Classes

Import and use the generated classes in your Python code:

```python
# Import generated classes
import voicevirtualagent_pb2 as voicevirtualagent__pb2
import voicevirtualagent_pb2_grpc as voicevirtualagent__pb2_grpc

# Use in your gRPC server
class MyServicer(voicevirtualagent__pb2_grpc.VoiceVirtualAgentServicer):
    def ListVirtualAgents(self, request, context):
        response = voicevirtualagent__pb2.ListVirtualAgentsResponse()
        # Populate response
        return response
    
    def ProcessCallerInput(self, request_iterator, context):
        for request in request_iterator:
            response = voicevirtualagent__pb2.VoiceVAResponse()
            # Process request and populate response
            yield response
```

## Best Practices

### Protocol Design

- **Backward Compatibility**: Design for backward compatibility
- **Field Numbers**: Never reuse field numbers in message definitions
- **Optional Fields**: Use optional fields for new additions
- **Documentation**: Include comprehensive comments in proto files

### Versioning

- **API Versioning**: Include version information in service names
- **Breaking Changes**: Plan breaking changes carefully
- **Migration Path**: Provide migration paths for API changes
- **Deprecation**: Mark deprecated fields appropriately

### Performance

- **Message Size**: Keep messages reasonably sized
- **Field Types**: Choose appropriate field types for data
- **Repeated Fields**: Use repeated fields for lists
- **Nested Messages**: Use nested messages for complex data

## Development Workflow

### 1. Modify Proto Files

Edit the `.proto` files to add new services or modify existing ones:

```protobuf
// Add new service method
service VoiceVirtualAgent {
  // Existing methods...
  
  // New method
  rpc GetAgentStatus(GetAgentStatusRequest) 
      returns (GetAgentStatusResponse);
}
```

### 2. Regenerate Code

After modifying proto files, regenerate the Python code:

```bash
# Clean up old generated files
rm src/core/*_pb2.py src/core/*_pb2_grpc.py

# Regenerate
python -m grpc_tools.protoc \
  -Iproto \
  --python_out=src/core \
  --grpc_python_out=src/core \
  proto/*.proto
```

### 3. Update Implementation

Update your Python code to use the new generated classes:

```python
# Update imports if needed
from voicevirtualagent_pb2 import GetAgentStatusRequest, GetAgentStatusResponse

# Implement new method
def GetAgentStatus(self, request, context):
    # Implementation
    pass
```

### 4. Test Changes

Test your changes to ensure compatibility:

```bash
# Test gRPC server
python main.py

# Test with client
python -c "
import grpc
import voicevirtualagent_pb2_grpc
channel = grpc.insecure_channel('localhost:50051')
stub = voicevirtualagent_pb2_grpc.VoiceVirtualAgentStub(channel)
"
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure generated files are in the correct location
2. **Version Mismatches**: Check protobuf and grpcio versions
3. **Field Number Conflicts**: Verify field numbers are unique
4. **Syntax Errors**: Validate proto file syntax

### Debug Commands

```bash
# Validate proto file syntax
protoc --proto_path=proto --descriptor_set_out=proto.pb proto/*.proto

# Check generated files
ls -la src/core/*_pb2*.py

# Test proto compilation
python -c "
import voicevirtualagent_pb2
print('Proto files compiled successfully')
"
```

### Version Compatibility

Ensure compatible versions of protobuf tools:

```bash
# Check versions
python -c "import grpc; print(f'gRPC: {grpc.__version__}')"
python -c "import google.protobuf; print(f'Protobuf: {google.protobuf.__version__}')"

# Update if needed
pip install --upgrade grpcio grpcio-tools protobuf
```

## Security Considerations

- **Input Validation**: Validate all protobuf messages
- **Size Limits**: Implement message size limits
- **Authentication**: Use gRPC interceptors for authentication
- **Encryption**: Use TLS for secure communication

## Performance Optimization

- **Message Pooling**: Reuse message objects when possible
- **Streaming**: Use streaming for large data transfers
- **Compression**: Enable gRPC compression
- **Caching**: Cache frequently used messages

## License

This code is licensed under the [Cisco Sample Code License v1.1](../LICENSE). See the main project README for details.

**Note**: Protocol Buffer definitions may be subject to their own licensing terms. Ensure compliance with all applicable licenses. 