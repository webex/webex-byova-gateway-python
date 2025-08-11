# Webex Contact Center BYOVA Gateway - Agent Guide

This document provides guidance for AI agents working with this codebase. It explains the architecture, design patterns, and conventions used in the Webex Contact Center BYOVA (Bring Your Own Virtual Agent) Gateway.

## Project Overview

The Webex Contact Center BYOVA Gateway is a Python-based gateway that acts as a bridge between Webex Contact Center (WxCC) and various virtual agent providers. It enables seamless voice interactions by implementing the required gRPC interfaces and routing requests to appropriate vendor-specific connector implementations.

### Purpose

The primary purpose of this gateway is to:
- Provide a flexible integration layer between WxCC and virtual agent platforms
- Abstract vendor-specific implementations behind a common interface
- Enable easy addition of new virtual agent connectors
- Provide monitoring and debugging capabilities

### Core Architecture

The gateway follows a modular architecture with the following key components:

```
                            ┌───────────────┐
                            │  WxCC gRPC    │
                            │   Interface   │
                            └───────┬───────┘
                                    │
                            ┌───────▼───────┐
                            │  Gateway      │
                            │   Server      │
                            └───────┬───────┘
                                    │
                            ┌───────▼───────┐
                            │ Virtual Agent │
                            │    Router     │
                            └───────┬───────┘
                                    │
           ┌────────────────┬──────┴───────┬─────────────────┐
           │                │              │                 │
┌──────────▼─────────┐    ┌─▼────────┐   ┌─▼──────────┐    ┌─▼────────────────┐
│  Local Audio        │    │ Vendor A │   │ Vendor B   │    │ Custom Connector │
│  Connector          │    │Connector │   │Connector   │    │    (Your impl)   │
└──────────┬──────────┘    └──────────┘   └────────────┘    └──────────────────┘
           │
    ┌──────▼──────┐
    │ Audio Files │
    └─────────────┘
```

## Project Structure

```
webex-byova-gateway-python/
├── audio/                    # Audio files for local connector
├── config/
│   └── config.yaml          # Main configuration file
├── proto/                    # Protocol Buffer definitions
├── src/
│   ├── connectors/           # Virtual agent connector implementations
│   │   ├── i_vendor_connector.py
│   │   └── local_audio_connector.py
│   ├── core/                # Core gateway components
│   │   ├── virtual_agent_router.py
│   │   ├── wxcc_gateway_server.py
│   │   └── *.py            # Generated gRPC stubs
│   └── monitoring/          # Web monitoring interface
│       ├── app.py
│       └── templates/
├── main.py                  # Main entry point
├── requirements.txt          # Python dependencies
└── README.md
```

## Key Components

### WxCCGatewayServer (`wxcc_gateway_server.py`)

- Implements the `VoiceVirtualAgentServicer` gRPC interface
- Manages conversation state through `ConversationProcessor` instances
- Handles bidirectional streaming for voice interactions
- Routes requests to the appropriate virtual agent via `VirtualAgentRouter`
- Tracks connections and manages session lifecycle

**Core Methods:**
- `ListVirtualAgents`: Returns available virtual agents
- `ProcessCallerInput`: Bidirectional streaming for voice interactions

### VirtualAgentRouter (`virtual_agent_router.py`)

- Loads and manages vendor connector instances
- Maintains agent-to-connector mappings
- Routes requests to the appropriate connector based on agent ID
- Provides connector and agent information for monitoring

**Core Methods:**
- `load_connectors`: Dynamically loads connector implementations from configuration
- `route_request`: Routes requests to the appropriate connector
- `get_connector_for_agent`: Retrieves the connector instance for a specific agent ID

### IVendorConnector (`i_vendor_connector.py`)

- Abstract base class defining the interface for vendor connectors
- All connector implementations must inherit from this class
- Provides a unified interface for vendor-specific implementations

**Required Implementations:**
- `start_conversation`: Initializes a new conversation with the virtual agent
- `send_message`: Sends audio or event data to the virtual agent
- `end_conversation`: Terminates a conversation
- `get_available_agents`: Returns a list of available agent IDs
- `convert_wxcc_to_vendor`: Converts from WxCC format to vendor format
- `convert_vendor_to_wxcc`: Converts from vendor format to WxCC format

### ConversationProcessor (`wxcc_gateway_server.py`)

- Manages state for an individual conversation
- Processes different input types (audio, DTMF, events)
- Converts between gRPC and connector formats
- Handles error conditions and conversation cleanup

## Development Guidelines

### Adding a New Connector

To add support for a new virtual agent platform:

1. Create a new connector class in `src/connectors/`
2. Inherit from `IVendorConnector` and implement all required methods
3. Implement vendor-specific logic in the connector class
4. Add configuration in `config/config.yaml`
5. Test with the monitoring interface

**Example Connector Structure:**
```python
from src.connectors.i_vendor_connector import IVendorConnector

class MyNewConnector(IVendorConnector):
    def __init__(self, config):
        self.api_key = config.get("api_key")
        self.endpoint = config.get("endpoint")
        # Initialize vendor-specific client/SDK
        
    def start_conversation(self, conversation_id, request_data):
        # Implement vendor-specific conversation start logic
        pass
        
    def send_message(self, conversation_id, message_data):
        # Implement vendor-specific message handling
        pass
        
    def end_conversation(self, conversation_id, message_data=None):
        # Implement vendor-specific conversation end logic
        pass
        
    def get_available_agents(self):
        return ["My Vendor Agent 1", "My Vendor Agent 2"]
        
    def convert_wxcc_to_vendor(self, grpc_data):
        # Convert WxCC format to vendor format
        pass
        
    def convert_vendor_to_wxcc(self, vendor_data):
        # Convert vendor format to WxCC format
        pass
```

### Configuration

The gateway is configured via `config/config.yaml`. Configuration should follow this structure:

```yaml
# Gateway settings
gateway:
  host: "0.0.0.0"
  port: 50051

# Monitoring interface
monitoring:
  enabled: true
  host: "0.0.0.0"
  port: 8080

# Connectors
connectors:
  - name: "connector_id"
    type: "connector_type"
    class: "ConnectorClassName"
    module: "connectors.module_name"
    config:
      # Connector-specific configuration
      api_key: "your_api_key"
      endpoint: "https://api.vendor.com"
```

## API Reference

### gRPC Interface

The gateway implements the `VoiceVirtualAgentServicer` interface with these methods:

- `ListVirtualAgents`: Returns available virtual agents
  - Input: `ListVirtualAgentsRequest`
  - Output: `ListVirtualAgentsResponse` with agent IDs and metadata
  
- `ProcessCallerInput`: Bidirectional streaming for voice interactions
  - Input: Stream of `VoiceVARequest` messages
  - Output: Stream of `VoiceVAResponse` messages

### HTTP Monitoring Interface

The web monitoring interface provides these endpoints:

- `GET /`: Main dashboard
- `GET /api/status`: Gateway status
- `GET /api/connections`: Connection data
- `GET /health`: Health check
- `GET /api/debug/sessions`: Debug information

## Testing

The gateway can be tested using:

1. **Direct gRPC Client Testing**
   - Use a gRPC client to call the gateway API directly
   - Generate test audio files for the local connector
   - Mock vendor responses for integration testing

2. **Web Interface Testing**
   - Use the monitoring interface to view connection status
   - Create test sessions via the debug API
   - Monitor real-time gateway metrics

3. **Load Testing**
   - Test with multiple simultaneous connections
   - Verify thread safety and resource management
   - Monitor memory usage under load

## Pull Request Guidelines

When submitting PRs to this project:

1. **Naming**
   - Use descriptive PR titles with prefix (e.g., "fix:", "feat:", "docs:")
   - Reference issue numbers if applicable

2. **Contents**
   - Include clear description of changes and rationale
   - Link to any related issues or documentation
   - List any breaking changes or dependencies

3. **Code Quality**
   - Ensure code follows project style guidelines
   - Include appropriate error handling and logging
   - Add tests for new functionality

4. **Documentation**
   - Update documentation for new features or changes
   - Add docstrings for new classes and methods
   - Update configuration examples if needed

## Coding Conventions

### Python Style Guidelines

- Follow PEP 8 style guide
- Use type annotations for function parameters and return values
- Document classes and methods with docstrings
- Use meaningful variable and function names
- Keep functions focused and concise

### Logging

- Use the built-in logging module
- Include appropriate log levels (DEBUG, INFO, WARNING, ERROR)
- Add context to log messages (e.g., conversation ID)
- Avoid excessive logging in normal operation

### Error Handling

- Use specific exception types
- Provide meaningful error messages
- Gracefully handle expected failure modes
- Log exceptions with stack traces at appropriate levels

## Working with the Codebase

To begin development:

1. **Create Virtual Environment**
   
   Always use a virtual environment to keep dependencies isolated:
   ```bash
   # Create a virtual environment in the project directory
   python -m venv venv
   ```

2. **Activate Virtual Environment**
   
   You must activate the virtual environment before running any code:
   ```bash
   # On macOS/Linux:
   source venv/bin/activate
   
   # On Windows:
   venv\Scripts\activate
   ```
   
   Your command prompt should now show the virtual environment name, e.g. `(venv)`.

3. **Install Dependencies**
   ```bash
   # Make sure you're in the activated virtual environment
   pip install -r requirements.txt
   ```

2. **Generate gRPC Stubs**
   ```bash
   python -m grpc_tools.protoc -I./proto --python_out=src/generated --grpc_python_out=src/generated proto/*.proto
   ```

3. **Run the Server**
   ```bash
   python main.py
   ```

4. **Access Monitoring Interface**
   - Open http://localhost:8080 in a browser
