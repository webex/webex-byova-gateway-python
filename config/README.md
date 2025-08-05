# Configuration

This directory contains configuration files for the Webex Contact Center BYOVA Gateway.

## Configuration Files

### `config.yaml`

The main configuration file that defines:

- **Connectors**: Vendor connector implementations and their settings
- **Gateway Settings**: Global gateway configuration
- **Monitoring**: Web interface and metrics configuration
- **Logging**: Log file settings and levels
- **Session Management**: Timeout and cleanup settings
- **Audio Processing**: Supported formats and limits

## Configuration Structure

### Connectors Section

Each connector is defined with:

```yaml
connectors:
  - name: "connector_name"           # Unique identifier
    type: "connector_type"           # Connector type
    class: "ClassName"               # Python class name
    module: "module.path"            # Python module path
    config:                          # Connector-specific settings
      key1: "value1"
      key2: "value2"
    agents:                          # List of agent IDs this connector provides
      - "Agent 1"
      - "Agent 2"
```

### Environment Variables

Configuration supports environment variable substitution:

```yaml
config:
  api_key: "${API_KEY}"             # Will be replaced with environment variable
  endpoint: "${VENDOR_ENDPOINT}"
```

### Example Connectors

#### Local Audio Connector
- **Purpose**: Testing and development
- **Features**: Plays local audio files
- **Use Case**: Development, demos, testing

#### Vendor X Connector (Example)
- **Purpose**: Integration with Vendor X platform
- **Features**: Real-time communication with Vendor X APIs
- **Use Case**: Production deployments

#### OpenAI Connector (Example)
- **Purpose**: AI-powered virtual agents
- **Features**: GPT model integration
- **Use Case**: AI-driven conversations

## Configuration Loading

The gateway loads configuration in this order:

1. **Default Configuration**: Built-in defaults
2. **Config File**: `config/config.yaml`
3. **Environment Variables**: Override specific settings
4. **Command Line Arguments**: Final overrides

## Validation

Configuration is validated on startup:

- Required fields are present
- Connector classes can be imported
- Audio files exist (for local connector)
- Network endpoints are reachable (for remote connectors)

## Security

- API keys should be stored as environment variables
- Sensitive configuration should not be committed to version control
- Use `.env` files for local development (not committed)

## Troubleshooting

### Common Issues

1. **Missing Connector Class**: Ensure the Python class exists and is importable
2. **Invalid Configuration**: Check YAML syntax and required fields
3. **Missing Audio Files**: Verify audio files exist for local connector
4. **Network Issues**: Check API endpoints for remote connectors

### Debug Mode

Enable debug logging to see detailed configuration loading:

```yaml
logging:
  level: "DEBUG"
``` 