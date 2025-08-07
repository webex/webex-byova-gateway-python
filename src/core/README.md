# Core Logic

This directory contains the core logic for the Webex Contact Center BYOVA Gateway, including the gRPC server implementation and virtual agent routing system.

## Components

### Virtual Agent Router (`virtual_agent_router.py`)

The router is responsible for:
- **Dynamic Connector Loading**: Loads connector implementations at runtime
- **Request Routing**: Routes incoming requests to appropriate virtual agents
- **Agent Management**: Manages agent selection and availability
- **Session Coordination**: Coordinates sessions across different connectors

**Key Methods**:
```python
class VirtualAgentRouter:
    def load_connectors(self, config: dict) -> None:
        """Load connector implementations from configuration"""
    
    def get_all_available_agents(self) -> list[str]:
        """Return all available agent IDs across all connectors"""
    
    def get_connector_for_agent(self, agent_id: str) -> IVendorConnector:
        """Get the connector instance for a specific agent"""
    
    def route_request(self, agent_id: str, method: str, *args, **kwargs) -> Any:
        """Route a request to the appropriate connector method"""
```

### WxCC Gateway Server (`wxcc_gateway_server.py`)

The gRPC server implements the `VoiceVirtualAgentServicer` interface:

- **ListVirtualAgents**: Returns available virtual agents to WxCC
- **ProcessCallerInput**: Handles bidirectional streaming for voice interactions
- **Session Management**: Tracks active sessions and connection events
- **Data Conversion**: Converts between WxCC gRPC format and vendor formats

**Key Features**:
- Bidirectional streaming for real-time voice communication
- Session lifecycle tracking (start, message, end events)
- Automatic session cleanup on stream termination
- Error handling and logging

### Generated gRPC Stubs

The following files are generated from Protocol Buffer definitions:

- `byova_common_pb2.py` - Common data structures
- `byova_common_pb2_grpc.py` - Common gRPC service definitions
- `voicevirtualagent_pb2.py` - Voice virtual agent data structures
- `voicevirtualagent_pb2_grpc.py` - Voice virtual agent service definitions

**Regeneration**:
```bash
# Regenerate stubs when proto files change
python -m grpc_tools.protoc -Iproto --python_out=src/core --grpc_python_out=src/core proto/byova_common.proto proto/voicevirtualagent.proto
```

## Architecture

### Request Flow

1. **WxCC Request**: WxCC sends gRPC request to gateway
2. **Router Lookup**: Gateway finds appropriate connector for agent
3. **Connector Processing**: Connector processes request in vendor format
4. **Response Conversion**: Response converted back to WxCC format
5. **Stream Response**: Response streamed back to WxCC

### Conversation Management

```python
# Conversation tracking in WxCCGatewayServer
self.active_conversations: Dict[str, Dict[str, Any]] = {
    "conversation_id": {
        "agent_id": "agent_name",
        "conversation_id": "conv_id",
        "customer_org_id": "org_id",
        "welcome_sent": True,
        "rpc_sessions": ["rpc_session_1", "rpc_session_2"]
    }
}

# Connection event tracking
self.connection_events = [
    {
        "event_type": "start|message|end",
        "conversation_id": "conversation_id",
        "agent_id": "agent_id",
        "timestamp": time.time(),
        "rpc_session_id": "rpc_session_id",
        **kwargs
    }
]
```

### Error Handling

The core components implement comprehensive error handling:

- **gRPC Status Codes**: Proper error codes returned to WxCC
- **Exception Logging**: Detailed error logging with context
- **Graceful Degradation**: System continues operating despite individual failures
- **Session Cleanup**: Automatic cleanup of failed sessions

## Configuration

Core components are configured via the main `config.yaml`:

```yaml
# Gateway settings
gateway:
  host: "0.0.0.0"
  port: 50051
  max_workers: 10

# Session management
sessions:
  timeout: 300  # seconds
  cleanup_interval: 60  # seconds
  max_sessions: 1000

# Logging
logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
```

## Development

### Adding New Features

1. **Extend Router**: Add new routing logic to `VirtualAgentRouter`
2. **Extend Server**: Add new gRPC methods to `WxCCGatewayServer`
3. **Update Stubs**: Regenerate gRPC stubs if proto files change
4. **Test Integration**: Test with WxCC and connectors

### Testing

```bash
# Unit tests for core components
python -m pytest tests/core/

# Integration tests
python -m pytest tests/integration/

# Load testing
python tests/load/test_gateway_load.py
```

### Performance Considerations

- **Connection Pooling**: Reuse connections to external services
- **Async Processing**: Use async/await for I/O operations
- **Memory Management**: Implement proper cleanup for large sessions
- **Monitoring**: Track performance metrics and bottlenecks

## Troubleshooting

### Common Issues

1. **gRPC Connection Errors**: Check network connectivity and firewall rules
2. **Session Leaks**: Monitor active sessions and implement cleanup
3. **Memory Issues**: Profile memory usage and optimize data structures
4. **Performance**: Monitor request latency and throughput

### Debug Mode

Enable detailed logging for troubleshooting:

```yaml
logging:
  level: "DEBUG"
  handlers:
    - type: "console"
      level: "DEBUG"
    - type: "file"
      filename: "logs/gateway_debug.log"
      level: "DEBUG"
```

## License

This code is licensed under the [Cisco Sample Code License v1.1](../LICENSE). See the main project README for details. 