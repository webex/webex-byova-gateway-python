# Core Logic

This directory contains the core logic for the Webex Contact Center BYOVA Gateway.

## Components

### Virtual Agent Router
- Routes incoming requests to appropriate virtual agents
- Handles agent selection and load balancing
- Manages agent state and availability

### gRPC Server
- Implements the gRPC service interface
- Handles incoming requests from Webex Contact Center
- Manages bidirectional streaming for real-time communication

## Architecture

The core components provide:
- Request routing and processing
- Agent management and coordination
- Protocol handling (gRPC, WebSocket, etc.)
- Configuration management
- Logging and monitoring integration 