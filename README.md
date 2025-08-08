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

2. **Create Virtual Environment**
   ```bash
   # Create virtual environment
   python -m venv venv

   # Activate virtual environment
   # On macOS/Linux:
   source venv/bin/activate
   # On Windows:
   # venv\Scripts\activate
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
   
   **Note**: The generated files use relative imports within the `src.generated` package. To use them in your code, import the package first:
   ```python
   import src.generated
   import byova_common_pb2
   import voicevirtualagent_pb2
   ```

5. **Prepare Audio Files**
   
   Place your audio files in the `audio/` directory. The default configuration expects:
   - `welcome.wav` - Welcome message
   - `default_response.wav` - Response messages
   - `goodbye.wav` - Goodbye message
   - `transferring.wav` - Transfer message
   - `error.wav` - Error message

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
  - name: "my_local_test_agent"
    type: "local_audio_connector"
    class: "LocalAudioConnector"
    module: "connectors.local_audio_connector"
    config:
      agent_id: "Local Playback"
      audio_base_path: "audio"
      audio_files:
        welcome: "welcome.wav"
        transfer: "transferring.wav"
        goodbye: "goodbye.wav"
        error: "error.wav"
        default: "default_response.wav"
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
- **Web Monitoring Interface**: Real-time dashboard for monitoring connections and status
- **Session Management**: Tracks active sessions and connection events
- **Extensible Architecture**: Easy to add new connector implementations

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

## Development

### Adding New Connectors

1. Create a new connector class in `src/connectors/`
2. Inherit from `IVendorConnector`
3. Implement required abstract methods
4. Add configuration to `config/config.yaml`
5. Restart the server

### gRPC Stub Generation

If you modify the `.proto` files:

```bash
# Regenerate stubs
python -m grpc_tools.protoc -Iproto --python_out=src/core --grpc_python_out=src/core proto/byova_common.proto proto/voicevirtualagent.proto
```

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

```bash
# Recreate virtual environment
rm -rf venv
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

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