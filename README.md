# Webex Contact Center BYOVA Gateway

[![License: Cisco Sample Code](https://img.shields.io/badge/License-Cisco%20Sample%20Code-blue.svg)](LICENSE)

A Python-based gateway for Webex Contact Center (WxCC) that provides virtual agent integration capabilities. This gateway acts as a bridge between WxCC and various virtual agent providers, enabling seamless voice interactions.

## 📚 Documentation

**Complete Setup Guide**: [BYOVA with AWS Lex Setup Guide](https://developer.webex.com/webex-contact-center/docs/byova-and-aws-lex)

This comprehensive guide walks you through:
- Setting up a Webex Contact Center sandbox
- Configuring BYOVA and BYODS
- Creating AWS Lex bots
- Deploying and testing the gateway

## Table of Contents

- [Install](#install)
- [Monitoring Dashboard](#monitoring-dashboard)
- [Usage](#usage)
- [API](#api)
- [Security Configuration](docs/Security-Configuration.md)
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
   git clone https://github.com/webex/webex-byova-gateway-python.git
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

3. **Install Dependencies** (Required)
   ```bash
   pip install -r requirements.txt
   ```
   
   **Important**: All dependencies including JWT authentication libraries are required. The gateway will not start if dependencies are missing.

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

## Monitoring Dashboard

The gateway includes a web-based monitoring interface for viewing gateway status, active sessions, and connection history. The dashboard is accessible at `http://localhost:8080` when the gateway is running.

For information about authentication and security for the monitoring dashboard, see:
- [Monitoring README](src/monitoring/README.md) - Comprehensive monitoring and authentication documentation
- [Authentication Quick Start](AUTHENTICATION_QUICKSTART.md) - Step-by-step authentication setup guide

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

The gateway is configured via `config/config.yaml`. Key configuration sections:

```yaml
# Gateway settings
gateway:
  host: "0.0.0.0"
  port: 50051

# Connectors configuration
connectors:
  # Local Audio Connector - plays audio files from the audio/ directory
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

  # AWS Lex Connector - integrates with Amazon Lex bots
  aws_lex_connector:
    type: "aws_lex_connector"
    class: "AWSLexConnector"
    module: "connectors.aws_lex_connector"
    config:
      region_name: "us-east-1"
      # bot_alias_id: "YOUR_BOT_ALIAS_ID"  # Required for specific bot
      # aws_access_key_id: "YOUR_ACCESS_KEY"  # Optional, uses env vars if not set
      # aws_secret_access_key: "YOUR_SECRET_KEY"  # Optional, uses env vars if not set
      initial_trigger_text: "hello"
      barge_in_enabled: false
      audio_logging:
        enabled: true
        output_dir: "logs/audio_recordings"
        filename_format: "{conversation_id}_{timestamp}_{source}.wav"
        log_all_audio: true
        max_file_size: 10485760
        sample_rate: 8000
        bit_depth: 8
        channels: 1
        encoding: "ulaw"
      agents: []

# Monitoring interface
monitoring:
  enabled: true
  host: "0.0.0.0"
  port: 8080
  metrics_enabled: true
  health_check_interval: 30

# Web dashboard authentication
authentication:
  enabled: true
  environment: "dev"  # Options: "dev" or "production"
  session:
    timeout_hours: 24
    secret_key_env: "FLASK_SECRET_KEY"
  webex_oauth:
    scopes: "openid email profile"
    state: "byova_gateway_auth"

# JWT validation for gRPC requests (REQUIRED when enabled)
jwt_validation:
  # Enable/disable JWT validation (default: true for security)
  enabled: true
  
  # Enforce validation - if false, invalid tokens are logged but allowed
  enforce_validation: true
  
  # REQUIRED: Datasource URL - must match URL registered with Webex Contact Center
  # Example: "https://your-gateway-domain.com:443"
  datasource_url: ""  # Must be configured if enabled=true
  
  # Datasource schema UUID (default is standard BYOVA schema)
  # This is the schema ID from https://github.com/webex/dataSourceSchemas
  # Path: Services/VoiceVirtualAgent/5397013b-7920-4ffc-807c-e8a3e0a18f43/schema.json
  # This value should not change unless there is a major modification to the BYOVA schema
  datasource_schema_uuid: "5397013b-7920-4ffc-807c-e8a3e0a18f43"
  
  # Public key cache duration in minutes
  cache_duration_minutes: 60

# Logging configuration
logging:
  gateway:
    level: "INFO"  # DEBUG, INFO, WARNING, ERROR
    format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file: "logs/gateway.log"
    max_size: "10MB"
    backup_count: 5
  web:
    level: "WARNING"
    format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file: "logs/web.log"
    max_size: "5MB"
    backup_count: 3

# Session management
sessions:
  timeout: 600  # Session timeout in seconds
  max_sessions: 1000
  cleanup_interval: 60
  enable_auto_cleanup: true
  max_session_duration: 3600

# Audio processing
audio:
  supported_formats:
    - "wav"
    - "mp3"
    - "flac"
    - "ogg"
```

#### Important Configuration Notes

**JWT Validation** (Required):
- JWT validation is **enabled by default** for security
- You **must** configure `datasource_url` before starting the gateway
- The `datasource_url` must exactly match the URL you register with Webex Contact Center via the BYoDS API
- If JWT validation is enabled without `datasource_url`, the gateway will **fail to start**
- For development without JWT validation, explicitly set `jwt_validation.enabled: false`

**Connector Configuration**:
- Multiple connectors can be configured simultaneously
- Each connector must have a unique identifier (e.g., `local_audio_connector`, `aws_lex_connector`)
- Connectors are loaded dynamically based on the `module` and `class` specified

**AWS Credentials**:
- Prefer environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`) over hardcoded credentials
- Explicit credentials in config files should only be used for development/testing

The connector uses the standard AWS credential chain (in order of precedence):
1. **Environment variables**: `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
2. **AWS credentials file**: `~/.aws/credentials`
3. **IAM roles**: For EC2, ECS, Lambda, and other AWS services
4. **AWS SSO**: If configured
5. **Other AWS credential sources**

**Examples:**

```bash
# Using environment variables (recommended for local development)
export AWS_ACCESS_KEY_ID=your_access_key_id
export AWS_SECRET_ACCESS_KEY=your_secret_access_key
export AWS_DEFAULT_REGION=us-east-1

# Or configure AWS CLI (recommended for persistent local setup)
aws configure

# For production, use IAM roles attached to your EC2/ECS/Lambda resources
# No credentials needed in config files!
```

You can add these lines to your shell profile (e.g., `.bashrc`, `.zshrc`) or set them in your deployment environment. The gateway will automatically use these credentials if they are set.

### JWT Authentication for gRPC Requests

The gateway supports JWT (JSON Web Token) validation for all gRPC requests to ensure secure communication with Webex Contact Center. This feature validates tokens from Webex identity broker endpoints and verifies all required claims.

#### Overview

JWT authentication provides:
- **Signature Verification**: Validates tokens using RSA public keys from Webex JWKS endpoints
- **Claims Validation**: Verifies issuer, audience, subject, JWT ID, and expiration
- **Datasource Validation**: Ensures tokens are issued for the correct datasource URL and schema
- **Caching**: Public keys are cached for 60 minutes to reduce endpoint load
- **Optional Enforcement**: Can be configured to log violations without rejecting requests

#### Configuration

JWT validation is configured in the `jwt_validation` section of `config/config.yaml`. See the [Configuration](#configuration) section above for the complete configuration structure.

**Key Points**:
- JWT validation is **enabled by default** (`enabled: true`)
- You **must** configure `datasource_url` or the gateway will fail to start
- Set `enabled: false` to disable JWT validation for development/testing

#### How to Obtain Your Datasource URL

The `datasource_url` must match the URL you register with Webex Contact Center when creating your datasource via the [BYoDS (Bring Your Own Data Source)](https://developer.webex.com/webex-contact-center/docs/api/v1/data-sources) API.

1. **For local development with ngrok**:
   ```
   datasource_url: "https://abc123def456.ngrok-free.app:443"
   ```

2. **For production deployment**:
   ```
   datasource_url: "https://byova-gateway.yourcompany.com:443"
   ```

**Important**: The URL must exactly match what you registered with Webex Contact Center, including the protocol (`https://`) and port (`:443` for HTTPS).

#### Understanding the Datasource Schema UUID

The `datasource_schema_uuid` identifies the specific schema definition used for communication between Webex Contact Center and your gateway. This UUID comes from the [Webex dataSourceSchemas repository](https://github.com/webex/dataSourceSchemas).

**For BYOVA (Voice Virtual Agent)**:
- **Schema UUID**: `5397013b-7920-4ffc-807c-e8a3e0a18f43`
- **Schema Location**: `Services/VoiceVirtualAgent/5397013b-7920-4ffc-807c-e8a3e0a18f43/schema.json`
- **Proto Definitions**: Defined in the same directory structure
- **Stability**: This UUID should **not change** unless there is a major modification to the BYOVA schema definition by Webex

**What is it?**
The schema UUID defines the structure of request and response payloads, protocol (gRPC), and supported app types. It ensures that both Webex Contact Center and your gateway are using the same communication protocol and message formats.

**Do I need to change it?**
In most cases, **no**. The default value is the standard BYOVA schema UUID and will work for all standard BYOVA implementations. You would only change this if:
- Webex releases a new major version of the BYOVA schema
- You're using a different Webex Contact Center service schema (not BYOVA)

**Reference**: [Webex dataSourceSchemas Documentation](https://github.com/webex/dataSourceSchemas)

#### Supported Webex Regions

The gateway validates tokens from these Webex identity broker issuers:
- `https://idbrokerbts.webex.com/idb` (BTS US)
- `https://idbrokerbts-eu.webex.com/idb` (BTS EU)
- `https://idbroker.webex.com/idb` (Production US)
- `https://idbroker-eu.webex.com/idb` (Production EU)
- `https://idbroker-b-us.webex.com/idb` (B-US)
- `https://idbroker-ca.webex.com/idb` (Canada)

#### Token Format

Tokens are expected in the gRPC metadata `authorization` header:
```
authorization: Bearer <JWT_TOKEN>
```

#### Deployment Recommendations

**Development**:
```yaml
jwt_validation:
  enabled: false  # Or enabled: true with enforce_validation: false for testing
```

**Production**:
```yaml
jwt_validation:
  enabled: true
  enforce_validation: true
  datasource_url: "https://your-production-url.com:443"
```

#### Troubleshooting

**Error: "Missing JWT token in authorization metadata"**
- Ensure Webex Contact Center is configured to send JWT tokens with gRPC requests
- Verify your datasource is properly registered with Webex Contact Center

**Error: "JWT token signature not valid"**
- Check that public keys can be fetched from Webex identity broker
- Verify your network allows outbound HTTPS connections to Webex endpoints

**Error: "Datasource URL mismatch"**
- Ensure `datasource_url` in config exactly matches the URL registered with Webex Contact Center
- Include the protocol (`https://`) and port (`:443`)

**Error: "JWT token is expired"**
- This indicates Webex Contact Center sent an expired token
- Check system clock synchronization between your gateway and Webex services

For gradual rollout, start with `enforce_validation: false` to log validation results without rejecting requests, then enable enforcement after verification.

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

### Public URL Hosting with ngrok

The [Bring Your Own Data Source (BYODS) framework](https://developer.webex.com/create/docs/bring-your-own-datasource) requires a publicly accessible URL for data exchange with Webex Contact Center. For development and testing, you can use ngrok to create a public URL that tunnels to your local gateway.

#### Prerequisites

1. **Install ngrok**
   - Download from [ngrok.com](https://ngrok.com/download)
   - Or install via package manager:
     ```bash
     # macOS with Homebrew
     brew install ngrok/ngrok/ngrok

     # Or download directly from ngrok.com
     ```

2. **Sign up for ngrok account** (free tier available)
   - Create account at [ngrok.com](https://ngrok.com)
   - Get your authtoken from the dashboard

3. **Configure ngrok**
   ```bash
   # Add your authtoken
   ngrok config add-authtoken YOUR_AUTHTOKEN
   ```

#### Running with ngrok

1. **Start the gateway** (in one terminal):
   ```bash
   # Activate virtual environment
   source venv/bin/activate

   # Start the gateway
   python main.py
   ```

2. **Start ngrok tunnel** (in another terminal):
   ```bash
   # Create public tunnel to the gRPC server
   ngrok http --upstream-protocol=http2 50051
   ```

   **Important**: Use the `--upstream-protocol=http2` flag as gRPC requires HTTP/2 protocol.

3. **Access your public gateway**:
   - ngrok will display a public URL like: `https://abc123.ngrok.io`
   - This URL can be used by external services to connect to your gateway
   - The monitoring interface will still be available locally at `http://localhost:8080`

4. **Register with Webex Data Sources API**:
   - Use the ngrok URL to register your data source with the [Webex Data Sources API](https://developer.webex.com/admin/docs/api/v1/data-sources/register-a-data-source)
   - This registration is required for Webex Contact Center to establish the BYODS connection
   - The registered URL will be used for all data exchange between Webex and your gateway

#### ngrok Dashboard

- Access the ngrok web interface at `http://localhost:4040` to monitor requests
- View real-time traffic, request/response details, and connection status
- Useful for debugging external connections to your gateway

#### Security Considerations

- **Development Only**: ngrok is intended for development and testing
- **Temporary URLs**: Free ngrok URLs change each time you restart ngrok
- **Public Access**: Anyone with the URL can access your gateway
- **Credentials**: Never expose production credentials through ngrok

#### Example Usage

```bash
# Terminal 1: Start gateway
source venv/bin/activate
python main.py

# Terminal 2: Start ngrok tunnel
ngrok http --upstream-protocol=http2 50051

# Output example:
# Forwarding  https://abc123.ngrok.io -> http://localhost:50051
#
# Use this URL in your Webex Contact Center configuration:
# https://abc123.ngrok.io
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

### gRPC Service Testing

Test the gRPC services directly using either grpcurl or the provided Python test script.

#### Using grpcurl

If you have grpcurl installed, you can test the gRPC services directly. Install grpcurl from the [releases page](https://github.com/fullstorydev/grpcurl/releases) for your platform.

**Test gRPC services:**
```bash
# Test overall health
grpcurl -plaintext -import-path proto -proto health.proto localhost:50051 grpc.health.v1.Health/Check

# Test gateway service health
grpcurl -plaintext -import-path proto -proto health.proto -d '{"service":"byova.gateway"}' localhost:50051 grpc.health.v1.Health/Check

# Test VoiceVirtualAgent service health
grpcurl -plaintext -import-path proto -proto health.proto -d '{"service":"byova.VoiceVirtualAgentService"}' localhost:50051 grpc.health.v1.Health/Check

# List available virtual agents
grpcurl -plaintext -import-path proto -proto voicevirtualagent.proto localhost:50051 com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent/ListVirtualAgents
```

**Expected outputs:**
```json
# Health checks return:
{"status": "SERVING"}

# Virtual agents list returns:
{
  "virtualAgents": [
    {
      "virtualAgentId": "Local Audio: Local Playback",
      "virtualAgentName": "Local Playback",
      "isDefault": true
    },
    {
      "virtualAgentId": "aws_lex_connector: YourBotName",
      "virtualAgentName": "YourBotName"
    }
  ]
}
```

#### Using Python Test Script

Alternatively, use the provided Python test script:

```bash
# Run the health check test script
python test_health.py
```

**Expected output:**
```
Testing gRPC Health Service:
----------------------------------------
Overall: SERVING (1)
byova.gateway: SERVING (1)
byova.VoiceVirtualAgentService: SERVING (1)
```

**Status codes:**
- `SERVING (1)`: Service is healthy and operational
- `NOT_SERVING (2)`: Service is unhealthy or unavailable
- `SERVICE_UNKNOWN (0)`: Service status cannot be determined

**Security Note:** gRPC reflection is disabled by default for security. This is why proto files are required for grpcurl commands.

## API

### gRPC Endpoints

- **ListVirtualAgents**: Returns available virtual agents
- **ProcessCallerInput**: Handles bidirectional streaming for voice interactions
- **Health/Check**: Standard gRPC health checking service

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

The protobuf definitions used in this gateway are sourced from the [Webex dataSourceSchemas repository](https://github.com/webex/dataSourceSchemas), specifically the Voice Virtual Agent schema. These definitions define the structure for BYOVA (Bring Your Own Virtual Agent) data exchange with Webex Contact Center.

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