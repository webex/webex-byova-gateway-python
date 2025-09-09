# Webex Contact Center BYOVA Gateway

[![License: Cisco Sample Code](https://img.shields.io/badge/License-Cisco%20Sample%20Code-blue.svg)](LICENSE)

A Python-based gateway for Webex Contact Center (WxCC) that provides virtual agent integration capabilities. This gateway acts as a bridge between WxCC and various virtual agent providers, enabling seamless voice interactions.

## Table of Contents

- [Install](#install)
- [Usage](#usage)
- [API](#api)
- [Maintainers](#maintainers)
- [Contributing](#contributing)
- [License](#license)

## Install

### Prerequisites

- Python 3.8 or higher
- macOS, Linux, or Windows
- Webex Contact Center environment for testing

### Setup

1. **Clone the Repository**
   ```bash
   git clone <repository-url>
   cd webex-byova-gateway-python
   ```

2. **Create and Activate Virtual Environment**
   ```bash
   # Create virtual environment
   python -m venv venv

   # Activate virtual environment (REQUIRED before running any commands)
   # On macOS/Linux:
   source venv/bin/activate
   # On Windows:
   # venv\Scripts\activate
   
   # Verify activation - you should see (venv) in your prompt
   which python  # Should show path to venv/bin/python
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Generate gRPC Stubs**
   ```bash
   # Generate Python gRPC client and server stubs in the generated directory
   python -m grpc_tools.protoc -I./proto --python_out=src/generated --grpc_python_out=src/generated proto/*.proto
   ```
   
   Generated protobuf files are stored in the `src/generated` directory to separate auto-generated code from hand-written code.
   
   **Important**: The generated protobuf files (`*_pb2.py` and `*_pb2_grpc.py`) are **NOT committed to the repository**. They must be generated locally after cloning the repository. The `__init__.py` file in the generated directory is committed to maintain the package structure.
   
   **Note**: The generated files are automatically imported by the gateway. No manual import is required for normal operation.

5. **Prepare Audio Files**
   
   Place your audio files in the `audio/` directory. The default configuration expects:
   - `welcome.wav` - Welcome message
   - `default_response.wav` - Response messages
   - `goodbye.wav` - Goodbye message
   - `transferring.wav` - Transfer message
   - `error.wav` - Error message

## Quick Start

For a quick test of the gateway:

1. **Activate virtual environment** (if not already active):
   ```bash
   source venv/bin/activate
   ```

2. **Generate gRPC stubs** (if not already done):
   ```bash
   python -m grpc_tools.protoc -I./proto --python_out=src/generated --grpc_python_out=src/generated proto/*.proto
   ```

3. **Start the server**:
   ```bash
   python main.py
   ```

4. **Access the monitoring interface**:
   - Open http://localhost:8080 in your browser
   - Check the status at http://localhost:8080/api/status

The gateway will start with the local audio connector by default, which uses the audio files in the `audio/` directory.

## Usage

### Configuration

The gateway is configured via `config/config.yaml`. Key configuration options:

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
  local_audio_connector:
    type: "local_audio_connector"
    class: "LocalAudioConnector"
    module: "connectors.local_audio_connector"
    config:
      audio_files:
        welcome: "welcome.wav"
        transfer: "transferring.wav"
        goodbye: "goodbye.wav"
        error: "error.wav"
        default: "default_response.wav"
      agents:
        - "Local Playback"
```

### Running the Server

#### Method 1: Manual Start (Recommended for Development)

```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Start the server
python main.py
```

The server will start both:
- **gRPC Server**: `grpc://0.0.0.0:50051`
- **Web Monitoring Interface**: `http://localhost:8080`

#### Method 2: Background Start

```bash
# Start in background
python main.py &

# Check if running
ps aux | grep "python main.py"

# Stop the server
pkill -f "python main.py"
```

### Monitoring Interface

Once the server is running, access the web monitoring interface at:

- **Main Dashboard**: `http://localhost:8080`
- **Status API**: `http://localhost:8080/api/status`
- **Connections API**: `http://localhost:8080/api/connections`
- **Health Check**: `http://localhost:8080/health`
- **Debug Info**: `http://localhost:8080/api/debug/sessions`

#### Dashboard Features

- **Real-time Status**: Gateway status and metrics
- **Active Connections**: Live session tracking
- **Connection History**: Recent connection events
- **Available Agents**: List of configured virtual agents
- **Configuration**: Gateway settings and connector info

### Testing

```bash
# Test the monitoring interface
curl http://localhost:8080/api/status

# Test connection tracking
curl http://localhost:8080/api/connections

# Create a test session (for development)
curl http://localhost:8080/api/test/create-session
```

## API

### gRPC Endpoints

- **ListVirtualAgents**: Returns available virtual agents
- **ProcessCallerInput**: Handles bidirectional streaming for voice interactions

### HTTP Endpoints

- `GET /`: Main dashboard
- `GET /api/status`: Gateway status
- `GET /api/connections`: Connection data
- `GET /health`: Health check
- `GET /api/debug/sessions`: Debug information

## Features

- **gRPC Server**: Handles communication with Webex Contact Center
- **Virtual Agent Router**: Dynamically routes requests to different connector implementations
- **Local Audio Connector**: Simulates virtual agents using local audio files
- **AWS Lex Connector**: Integration with Amazon Lex v2 for production virtual agents
- **Web Monitoring Interface**: Real-time dashboard for monitoring connections and status
- **Session Management**: Tracks active sessions and connection events
- **Extensible Architecture**: Easy to add new connector implementations

## Connector Documentation

This gateway supports multiple virtual agent connectors. Each connector has its own documentation:

- **[Connectors Overview](src/connectors/README.md)**: Complete guide to all available connectors and how to create new ones
- **[Local Audio Connector](src/connectors/README.md#local-audio-connector-local_audio_connectorpy)**: Testing and development with local audio files
- **[AWS Lex Connector](src/connectors/README.md#aws-lex-connector-aws_lex_connectorpy)**: Production integration with Amazon Lex v2
- **[Audio Files Guide](audio/README.md)**: Audio file formats, organization, and configuration

## Project Structure

```
webex-byova-gateway-python/
├── audio/                    # Audio files for local connector
├── config/
│   ├── config.yaml          # Main configuration file
│   └── aws_lex_example.yaml # AWS Lex configuration example
├── proto/                    # Protocol Buffer definitions
├── src/
│   ├── connectors/           # Virtual agent connector implementations
│   │   ├── i_vendor_connector.py
│   │   ├── local_audio_connector.py
│   │   ├── aws_lex_connector.py
│   │   └── README.md
│   ├── core/                # Core gateway components
│   │   ├── virtual_agent_router.py
│   │   └── wxcc_gateway_server.py
│   ├── generated/           # Generated gRPC stubs
│   │   ├── byova_common_pb2.py
│   │   ├── byova_common_pb2_grpc.py
│   │   ├── voicevirtualagent_pb2.py
│   │   └── voicevirtualagent_pb2_grpc.py
│   ├── monitoring/          # Web monitoring interface
│   │   ├── app.py
│   │   └── templates/
│   └── utils/               # Utility modules
├── main.py                  # Main entry point
├── requirements.txt          # Python dependencies
└── README.md
```

## Development

### Adding New Connectors

1. Create a new connector class in `src/connectors/`
2. Inherit from `IVendorConnector`
3. Implement required abstract methods
4. Add configuration to `config/config.yaml`
5. Restart the server

### gRPC Stub Generation

If you modify the `.proto` files, you must regenerate the Python stubs:

```bash
# Regenerate stubs
python -m grpc_tools.protoc -I./proto --python_out=src/generated --grpc_python_out=src/generated proto/*.proto
```

**Note**: The generated files are automatically ignored by git (see `.gitignore`). After regenerating, the files will be available locally but won't be committed to the repository.

## Troubleshooting

### Port Conflicts

If port 8080 is in use:

```bash
# Check what's using the port
lsof -i :8080

# Kill the process
kill <PID>

# Or change the port in config/config.yaml
```

### Virtual Environment Issues

**Problem**: `python: command not found` or import errors

**Solution**: Ensure virtual environment is activated before running any Python commands:

```bash
# Check if virtual environment is activated
echo $VIRTUAL_ENV  # Should show path to venv directory

# If not activated, activate it
source venv/bin/activate

# Verify Python is from virtual environment
which python  # Should show .../venv/bin/python

# Recreate virtual environment if needed
rm -rf venv
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Important**: Always activate the virtual environment before running `python main.py` or any other Python commands.

### Logs

The server provides detailed logging:
- **INFO**: General operation information
- **DEBUG**: Detailed request/response tracking
- **ERROR**: Error conditions and exceptions

Check the terminal output for real-time logs when running manually.

## Maintainers

[@adweeks](https://github.com/adweeks)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

[Cisco Sample Code License v1.1](LICENSE) © 2018 Cisco and/or its affiliates

---

**Note**: This Sample Code is not supported by Cisco TAC and is not tested for quality or performance. This is intended for example purposes only and is provided by Cisco "AS IS" with all faults and without warranty or support of any kind. 