# Connectors

This directory contains vendor connector implementations for the Webex Contact Center BYOVA Gateway.

## Purpose

Connectors handle communication with different vendor systems and platforms, providing a unified interface for the core gateway. They implement the `IVendorConnector` abstract base class to ensure consistent behavior across different virtual agent providers.

## Architecture

### Abstract Base Class

All connectors must implement `IVendorConnector` which defines:

- **Session Management**: `start_session()`, `end_session()`
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
    def start_session(self, session_id: str, request_data: dict) -> dict:
        """Start a virtual agent session"""
        pass
    
    @abstractmethod
    def send_message(self, session_id: str, message_data: dict) -> dict:
        """Send a message/audio to the virtual agent"""
        pass
    
    @abstractmethod
    def end_session(self, session_id: str) -> None:
        """End a virtual agent session"""
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
        welcome: "test-welcome.wav"
        transfer: "test-response.wav"
        goodbye: "test-goodbye.wav"
```

## Adding New Connectors

### 1. Create Connector Class

```python
from connectors.i_vendor_connector import IVendorConnector

class MyVendorConnector(IVendorConnector):
    def __init__(self, config: dict) -> None:
        # Initialize with configuration
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    def start_session(self, session_id: str, request_data: dict) -> dict:
        # Implement session start logic
        return {"status": "started", "message": "Welcome"}
    
    def send_message(self, session_id: str, message_data: dict) -> dict:
        # Implement message handling
        return {"status": "processed", "response": "Hello"}
    
    def end_session(self, session_id: str) -> None:
        # Implement session cleanup
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