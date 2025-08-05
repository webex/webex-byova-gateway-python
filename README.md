# Webex Contact Center BYOVA Gateway Python

A Python implementation of the Webex Contact Center BYOVA (Bring Your Own Virtual Agent) Gateway.

## Project Structure

```
webex-byova-gateway-python/
├── audio/                 # Placeholder audio files for local connector
├── proto/                 # Protocol Buffer definitions
├── src/                   # Python source code
│   ├── connectors/        # Vendor connector implementations
│   ├── core/             # Core logic (Virtual Agent Router, gRPC server)
│   └── monitoring/       # Web-based monitoring interface
└── requirements.txt       # Python dependencies
```

## Overview

This gateway acts as a bridge between Webex Contact Center and virtual agent platforms, enabling organizations to integrate their own virtual agents with Webex Contact Center.

### Key Components

- **Virtual Agent Router**: Routes incoming requests to appropriate virtual agents
- **gRPC Server**: Handles communication with Webex Contact Center
- **Connectors**: Interface with different vendor platforms
- **Monitoring Interface**: Web-based dashboard for system monitoring

## Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Configure your environment variables

3. Start the gateway:
   ```bash
   python -m src.core.server
   ```

## Development

- **Core Logic**: Implemented in `src/core/`
- **Connectors**: Add new vendor connectors in `src/connectors/`
- **Monitoring**: Web interface in `src/monitoring/`
- **Protocols**: Define interfaces in `proto/`

## Dependencies

See `requirements.txt` for the complete list of Python dependencies, including:
- gRPC for communication
- Flask for monitoring interface
- Audio processing libraries
- Logging and monitoring tools 