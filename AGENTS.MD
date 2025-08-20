# Webex Contact Center BYOVA Gateway - Agent Guide

> **⚠️ IMPORTANT: This is a Functional Example, Not Production-Ready**
> 
> This project is designed as a **functional example** for customers and developers building on BYOVA (Bring Your Own Virtual Agent). It demonstrates best practices for coding and well-documented methods for interfacing with BYOVA, but it is **NOT intended to be a fully production-ready application**.
> 
> **Purpose**: This gateway serves as a reference implementation that customers can:
> - **Fork and build upon** for their own implementations
> - **Extract specific parts and pieces** they need to understand BYOVA integration
> - **Learn best practices** for connecting to different voice agent services
> - **Use as a starting point** for their own BYOVA integrations

This document provides guidance for AI agents working with this codebase. It explains the architecture, design patterns, and conventions used in the Webex Contact Center BYOVA (Bring Your Own Virtual Agent) Gateway.

## Project Overview

The Webex Contact Center BYOVA Gateway is a Python-based gateway that acts as a bridge between Webex Contact Center (WxCC) and various virtual agent providers. It enables seamless voice interactions by implementing the required gRPC interfaces and routing requests to appropriate vendor-specific connector implementations.

### Purpose

The primary purpose of this gateway is to:
- **Serve as a functional example** for customers implementing BYOVA integrations
- **Demonstrate best practices** for coding and documentation
- **Provide a flexible integration layer** between WxCC and virtual agent platforms
- **Abstract vendor-specific implementations** behind a common interface
- **Enable easy addition of new virtual agent connectors** through well-defined patterns
- **Provide monitoring and debugging capabilities** for development and testing
- **Show customers how to interface with BYOVA** through practical, working code

### Target Audience

This gateway is specifically designed for:
- **Developers** who need to understand BYOVA integration patterns
- **Customers** who want to build their own voice agent integrations
- **Architects** who need to understand the design patterns for BYOVA
- **DevOps teams** who want to see examples of monitoring and deployment patterns

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

### Educational and Reference Purpose

This gateway is designed to be **educational and instructive** for customers implementing BYOVA integrations. When working with this codebase:

- **Study the patterns**: Each connector demonstrates how to properly implement the BYOVA interface
- **Learn from examples**: The existing connectors show real-world integration approaches
- **Use as templates**: Copy and modify connector patterns for your own implementations
- **Understand best practices**: The code follows enterprise-grade coding standards and patterns
- **Reference the architecture**: Use the modular design as a blueprint for your own systems

### Adding a New Connector

To add support for a new virtual agent platform (or to learn how to create your own):

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

## How Customers Should Use This Project

### For Learning and Understanding BYOVA

This gateway serves as a **comprehensive learning resource** for BYOVA integration:

- **Read the code**: Study how the gRPC interfaces are implemented
- **Examine connectors**: Understand how different voice agent services are integrated
- **Follow the patterns**: Use the established architectural patterns in your own code
- **Reference the interfaces**: Use the abstract base classes as contracts for your implementations

### For Building Your Own Implementation

When building your own BYOVA integration:

- **Fork this repository**: Use it as a starting point for your project
- **Extract components**: Take only the parts you need (e.g., just the base connector interface)
- **Customize connectors**: Modify existing connectors or create new ones for your vendors
- **Adapt the architecture**: Use the modular design as inspiration for your system

### For Production Use

**Important**: This gateway is not production-ready. For production use:

- **Implement proper security**: Add authentication, authorization, and encryption
- **Add production monitoring**: Implement comprehensive logging, metrics, and alerting
- **Handle scaling**: Design for horizontal scaling and load balancing
- **Add error handling**: Implement robust error handling and recovery mechanisms
- **Security review**: Conduct thorough security reviews before deployment

## Working with the Codebase

To begin development (for learning or building upon this example):
   
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

## AI Agent Development Guidelines

### Working with AI Agents (Like Me)

This section provides specific guidance for AI agents working with this codebase to ensure effective development and accurate assistance.

#### Code Understanding Patterns

When analyzing this codebase as an AI agent:

- **Start with the interfaces**: Always examine `i_vendor_connector.py` first to understand the contract
- **Follow the data flow**: Trace requests from `wxcc_gateway_server.py` → `virtual_agent_router.py` → specific connectors
- **Study the generated code**: The `src/generated/` directory contains the gRPC stubs that define the API contract
- **Check configuration patterns**: Look at `config/config.yaml` to understand how connectors are loaded and configured

#### Common AI Agent Tasks and Solutions

**Adding New Connectors:**
- Use existing connectors as templates (e.g., `local_audio_connector.py`)
- Ensure all abstract methods from `IVendorConnector` are implemented
- Follow the error handling patterns established in existing connectors
- Add appropriate logging and monitoring hooks

**Debugging Integration Issues:**
- Check the monitoring interface at `/api/debug/sessions` for real-time session data
- Review logs for conversation flow and error conditions
- Verify gRPC message format conversions in `convert_wxcc_to_vendor` and `convert_vendor_to_wxcc`
- Test with the local audio connector first before integrating external services

**Code Quality and Standards:**
- Follow the established error handling patterns in `error_handling.py`
- Use the logging patterns demonstrated throughout the codebase
- Maintain the modular architecture when adding new features
- Ensure all new code includes proper docstrings and type hints

#### AI Agent Best Practices for This Codebase

1. **Always check the virtual environment**: Remind users to activate `venv` before running Python code
2. **Verify gRPC stub generation**: Ensure proto files are compiled before testing
3. **Test incrementally**: Start with local connector before external integrations
4. **Use the monitoring interface**: Leverage the built-in web interface for debugging
5. **Follow the established patterns**: Don't reinvent architecture - extend what exists

#### Common Pitfalls for AI Agents

- **Missing virtual environment activation**: Always check if `venv` is activated
- **Forgotten gRPC compilation**: Proto files must be compiled to generate Python stubs
- **Configuration mismatches**: Ensure connector configs match the expected format in `config.yaml`
- **Interface violations**: New connectors must implement ALL methods from `IVendorConnector`
- **Error handling gaps**: Follow the established error handling patterns in the codebase

#### AI Agent Workflow for This Codebase

**When a user asks to add a new feature:**

1. **Analyze the request**: Understand what type of connector or functionality is needed
2. **Examine existing patterns**: Look at similar implementations in the codebase
3. **Check the interface**: Ensure the new feature follows the established `IVendorConnector` contract
4. **Plan the implementation**: Break down the task into logical steps
5. **Implement incrementally**: Start with the core functionality, then add error handling and logging
6. **Test the integration**: Use the monitoring interface and local connector for validation
7. **Document the changes**: Update relevant documentation and add proper docstrings

**When debugging issues:**

1. **Check the monitoring interface**: Start at `/api/debug/sessions` for real-time data
2. **Review the logs**: Look for error patterns and conversation flow issues
3. **Verify configuration**: Ensure all config values are properly set
4. **Test with known good data**: Use the local connector to isolate issues
5. **Check gRPC message formats**: Verify conversions between WxCC and vendor formats

**When explaining concepts to users:**

1. **Start with the architecture**: Show how the modular design works
2. **Use concrete examples**: Reference specific files and methods in the codebase
3. **Explain the data flow**: Walk through how requests move through the system
4. **Highlight best practices**: Point out the established patterns and why they exist
5. **Provide working examples**: Give users code they can actually run and test

#### Quick Reference for AI Agents

**Key Files to Know:**
- `src/connectors/i_vendor_connector.py` - Abstract base class for all connectors
- `src/connectors/local_audio_connector.py` - Working example connector
- `src/core/wxcc_gateway_server.py` - Main gRPC server implementation
- `src/core/virtual_agent_router.py` - Routes requests to appropriate connectors
- `config/config.yaml` - Configuration for connectors and gateway settings
- `proto/` - Protocol buffer definitions for gRPC interfaces

**Common Patterns:**
- All connectors inherit from `IVendorConnector` and implement its abstract methods
- Configuration-driven connector loading in `VirtualAgentRouter`
- Bidirectional streaming for voice interactions in `ProcessCallerInput`
- Error handling through dedicated error handling modules
- Monitoring and debugging via web interface at port 8080

**Testing Approaches:**
- Use local audio connector for initial testing and validation
- Monitor real-time data via `/api/debug/sessions` endpoint
- Check logs for conversation flow and error conditions
- Test gRPC message format conversions thoroughly
- Validate configuration changes through the monitoring interface

## Conclusion

This BYOVA Gateway serves as a **functional example and reference implementation** for customers and developers working with BYOVA. It demonstrates:

- **Best practices** for implementing BYOVA gRPC interfaces
- **Modular architecture** that can be adapted for different use cases
- **Well-documented code** that serves as a learning resource
- **Extensible connector system** that shows how to integrate various voice agent services

**Remember**: This is not a production-ready application, but rather a **comprehensive example** that customers can use to understand, learn from, and build upon for their own BYOVA integrations. The code quality, documentation, and architectural patterns are designed to serve as a reference for enterprise-grade BYOVA implementations.

For questions about BYOVA integration or this reference implementation, please refer to the official BYOVA documentation or contact your Webex Contact Center representative.
