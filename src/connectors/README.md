# Connectors

This directory contains vendor connector implementations for the Webex Contact Center BYOVA Gateway.

## Purpose

Connectors handle communication with different vendor systems and platforms, providing a unified interface for the core gateway. They implement the `IVendorConnector` abstract base class to ensure consistent behavior across different virtual agent providers.

## Architecture

### Abstract Base Class

All connectors must implement `IVendorConnector` which defines:

- **Conversation Management**: `start_conversation()`, `end_conversation()`
- **Message Handling**: `send_message()`
- **Agent Discovery**: `get_available_agents()`
- **Data Conversion**: `convert_wxcc_to_vendor()`, `convert_vendor_to_wxcc()`

### Interface Contract

```python
class IVendorConnector(ABC):
    @abstractmethod
    def __init__(self, config: dict) -> None:
        """Initialize connector with configuration"""
        pass
    
    @abstractmethod
    def start_conversation(self, conversation_id: str, request_data: dict) -> dict:
        """Start a virtual agent conversation"""
        pass
    
    @abstractmethod
    def send_message(self, conversation_id: str, message_data: dict) -> dict:
        """Send a message/audio to the virtual agent"""
        pass
    
    @abstractmethod
    def end_conversation(self, conversation_id: str, message_data: dict = None) -> None:
        """End a virtual agent conversation"""
        pass
    
    @abstractmethod
    def get_available_agents(self) -> list[str]:
        """Return list of available agent IDs"""
        pass
```

## Available Connectors

### Local Audio Connector (`local_audio_connector.py`)

**Purpose**: Testing and development with local audio files

**Features**:
- Plays predefined audio files for different scenarios
- Simulates virtual agent responses
- Supports welcome, transfer, and goodbye messages
- Ideal for development and testing

**Configuration**:
```yaml
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

### AWS Lex Connector (`aws_lex_connector.py`)

**Purpose**: Integration with Amazon Lex v2 for virtual agent capabilities

**Features**:
- Connects to existing AWS Lex v2 instances
- Automatically discovers and lists available Lex bots as agents
- Supports multiple AWS credential methods
- Foundation for full conversation handling

**Prerequisites**:
1. AWS account with Lex v2 bots configured
2. AWS credentials configured (via AWS CLI, environment variables, or IAM roles)
3. Python packages: `boto3` and `botocore`

**Configuration**:
```yaml
connectors:
  - name: "aws_lex_connector_dev"
    type: "aws_lex_connector"
    class: "AWSLexConnector"
    module: "connectors.aws_lex_connector"
    config:
      region_name: "us-east-1"  # Your AWS region
      bot_alias_id: "TSTALIASID"  # Your Lex bot alias
      aws_access_key_id: "YOUR_DEV_ACCESS_KEY"  # Explicit AWS access key (for dev only)
      aws_secret_access_key: "YOUR_DEV_SECRET_KEY"  # Explicit AWS secret (for dev only)
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
```


**Note:** For production, use environment variables or IAM roles for credentials. Explicit credentials in config files are for development/testing only.

### Setting AWS Credentials with Environment Variables

For production or secure development, set your AWS credentials as environment variables instead of hardcoding them in your config file:

```sh
export AWS_ACCESS_KEY_ID=your_access_key
export AWS_SECRET_ACCESS_KEY=your_secret_key
```

You can add these lines to your shell profile (e.g., `.bashrc`, `.zshrc`) or set them in your deployment environment. The connector will automatically use these credentials if they are set.

**AWS Credentials**:
The connector supports multiple ways to provide AWS credentials:

1. **Default credentials** (recommended): Configure via AWS CLI (`aws configure`) or environment variables
2. **Explicit credentials**: Provide in config file (less secure)
3. **IAM roles**: When running on EC2 or ECS with appropriate IAM roles

**Current Limitations**:
- Basic connectivity and bot listing only
- Full conversation handling not yet implemented
- Audio processing integration pending

## Adding New Connectors

### 1. Create Connector Class

```python
from connectors.i_vendor_connector import IVendorConnector

class MyVendorConnector(IVendorConnector):
    def __init__(self, config: dict) -> None:
        # Initialize with configuration
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    def start_conversation(self, conversation_id: str, request_data: dict) -> dict:
        # Implement conversation start logic
        return {"status": "started", "message": "Welcome"}
    
    def send_message(self, conversation_id: str, message_data: dict) -> dict:
        # Implement message handling
        return {"status": "processed", "response": "Hello"}
    
    def end_conversation(self, conversation_id: str, message_data: dict = None) -> None:
        # Implement conversation cleanup
        pass
    
    def get_available_agents(self) -> list[str]:
        # Return available agent IDs
        return ["My Agent 1", "My Agent 2"]
```

### 2. Add Configuration

```yaml
connectors:
  - name: "my_vendor_connector"
    type: "my_vendor"
    class: "MyVendorConnector"
    module: "connectors.my_vendor_connector"
    config:
      api_key: "${MY_VENDOR_API_KEY}"
      endpoint: "https://api.myvendor.com"
      timeout: 30
```

### 3. Test Implementation

```bash
# Test connector loading
python -c "from src.connectors.my_vendor_connector import MyVendorConnector; print('OK')"

# Test with gateway
python main.py
```

## Best Practices

### Error Handling
- Implement proper exception handling
- Log errors with context
- Return meaningful error responses

### Configuration
- Use environment variables for sensitive data
- Validate configuration on initialization
- Provide sensible defaults

### Logging
- Use structured logging
- Include session IDs in log messages
- Log at appropriate levels (DEBUG, INFO, ERROR)

### Testing
- Write unit tests for each connector
- Test error conditions
- Mock external dependencies

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure connector class is properly imported
2. **Configuration Errors**: Validate YAML syntax and required fields
3. **Session Management**: Implement proper session cleanup
4. **Data Conversion**: Handle WxCC format conversion correctly

### Debug Mode

Enable debug logging to see detailed connector behavior:

```yaml
logging:
  level: "DEBUG"
```

## License

This code is licensed under the [Cisco Sample Code License v1.1](LICENSE). See the main project README for details. 