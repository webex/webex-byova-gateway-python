# Configuration

This directory contains configuration files for the Webex Contact Center BYOVA Gateway, providing centralized management of gateway settings, connectors, and system behavior.

## Configuration Files

### `config.yaml`

The main configuration file that defines all gateway settings:

- **Connectors**: Vendor connector implementations and their settings
- **Gateway Settings**: Global gateway configuration and behavior
- **Monitoring**: Web interface and metrics configuration
- **Logging**: Log file settings, levels, and formatting
- **Session Management**: Timeout, cleanup, and session limits
- **Audio Processing**: Supported formats, limits, and processing options
- **Security**: Authentication, encryption, and access control settings

## Configuration Structure

### Gateway Settings

```yaml
# Gateway configuration
gateway:
  host: "0.0.0.0"
  port: 50051
  max_workers: 10
  timeout: 30
  enable_tls: false
  cert_file: ""
  key_file: ""
```

### Connectors Section

Each connector is defined with comprehensive settings:

```yaml
connectors:
  - name: "connector_name"           # Unique identifier
    type: "connector_type"           # Connector type
    class: "ClassName"               # Python class name
    module: "module.path"            # Python module path
    enabled: true                    # Enable/disable connector
    config:                          # Connector-specific settings
      key1: "value1"
      key2: "value2"
      api_key: "${API_KEY}"          # Environment variable substitution
      endpoint: "${VENDOR_ENDPOINT}"
    agents:                          # List of agent IDs this connector provides
      - "Agent 1"
      - "Agent 2"
    health_check:                    # Health check configuration
      enabled: true
      interval: 30
      timeout: 5
```

### Monitoring Configuration

```yaml
monitoring:
  enabled: true
  host: "0.0.0.0"
  port: 8080
  debug: false
  metrics_enabled: true
  health_check_interval: 30
  cors_enabled: true
  allowed_origins:
    - "http://localhost:3000"
    - "https://yourdomain.com"
```

### Logging Configuration

```yaml
logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  handlers:
    - type: "console"
      level: "INFO"
    - type: "file"
      filename: "logs/gateway.log"
      level: "DEBUG"
      max_bytes: 10485760  # 10MB
      backup_count: 5
  loggers:
    grpc: "WARNING"
    urllib3: "WARNING"
```

### Session Management

```yaml
sessions:
  timeout: 300                    # Session timeout in seconds
  cleanup_interval: 60           # Cleanup interval in seconds
  max_sessions: 1000             # Maximum concurrent sessions
  max_session_duration: 3600     # Maximum session duration
  enable_auto_cleanup: true      # Enable automatic session cleanup
```

## Environment Variable Support

Configuration supports environment variable substitution for sensitive data:

```yaml
config:
  api_key: "${API_KEY}"             # Will be replaced with environment variable
  endpoint: "${VENDOR_ENDPOINT}"
  database_url: "${DATABASE_URL}"
  secret_key: "${SECRET_KEY}"
```

### Environment Variable Loading

The gateway supports multiple ways to load environment variables:

1. **System Environment**: Variables set in the system environment
2. **`.env` File**: Local development environment file
3. **Docker Environment**: Container environment variables
4. **Kubernetes Secrets**: Kubernetes secret management

## Example Connectors

### Local Audio Connector

**Purpose**: Testing and development with local audio files

```yaml
connectors:
  - name: "my_local_test_agent"
    type: "local_audio_connector"
    class: "LocalAudioConnector"
    module: "connectors.local_audio_connector"
    enabled: true
    config:
      agent_id: "Local Playback"
      audio_base_path: "audio"
      audio_files:
        welcome: "welcome.wav"
        transfer: "transferring.wav"
        goodbye: "goodbye.wav"
        error: "error.wav"
        default: "default_response.wav"
      playback_settings:
        volume: 1.0
        speed: 1.0
        format: "wav"
```

### Vendor X Connector (Example)

**Purpose**: Integration with Vendor X platform

```yaml
connectors:
  - name: "vendor_x_connector"
    type: "vendor_x"
    class: "VendorXConnector"
    module: "connectors.vendor_x_connector"
    enabled: true
    config:
      api_key: "${VENDOR_X_API_KEY}"
      endpoint: "${VENDOR_X_ENDPOINT}"
      timeout: 30
      retry_attempts: 3
      authentication:
        type: "bearer"
        token: "${VENDOR_X_TOKEN}"
      features:
        speech_to_text: true
        text_to_speech: true
        natural_language: true
    agents:
      - "Vendor X Agent 1"
      - "Vendor X Agent 2"
```

### OpenAI Connector (Example)

**Purpose**: AI-powered virtual agents

```yaml
connectors:
  - name: "openai_connector"
    type: "openai"
    class: "OpenAIConnector"
    module: "connectors.openai_connector"
    enabled: true
    config:
      api_key: "${OPENAI_API_KEY}"
      model: "gpt-4"
      max_tokens: 1000
      temperature: 0.7
      system_prompt: "You are a helpful virtual assistant."
      features:
        conversation_memory: true
        context_awareness: true
        multi_language: true
    agents:
      - "AI Assistant"
      - "Customer Support Bot"
```

## Configuration Loading

The gateway loads configuration in this order:

1. **Default Configuration**: Built-in defaults for all settings
2. **Config File**: `config/config.yaml` (overrides defaults)
3. **Environment Variables**: Override specific settings
4. **Command Line Arguments**: Final overrides for runtime settings

### Configuration Validation

Configuration is validated on startup:

- **Required Fields**: Ensure all required fields are present
- **Connector Classes**: Verify connector classes can be imported
- **File Existence**: Check that referenced files exist (audio files, certificates)
- **Network Connectivity**: Test API endpoints for remote connectors
- **Type Validation**: Validate data types and value ranges

### Configuration Hot Reloading

The gateway supports hot reloading of certain configuration sections:

```yaml
# Enable hot reloading
config:
  hot_reload:
    enabled: true
    watch_interval: 30
    reloadable_sections:
      - "logging"
      - "monitoring"
      - "sessions"
```

## Security Configuration

### Authentication and Authorization

```yaml
security:
  authentication:
    enabled: true
    type: "jwt"
    secret_key: "${JWT_SECRET_KEY}"
    token_expiry: 3600
  authorization:
    enabled: true
    roles:
      - "admin"
      - "operator"
      - "viewer"
  encryption:
    enabled: true
    algorithm: "AES-256-GCM"
    key: "${ENCRYPTION_KEY}"
```

### Network Security

```yaml
network:
  tls:
    enabled: false
    cert_file: "certs/server.crt"
    key_file: "certs/server.key"
    ca_file: "certs/ca.crt"
  firewall:
    allowed_ips:
      - "192.168.1.0/24"
      - "10.0.0.0/8"
  rate_limiting:
    enabled: true
    requests_per_minute: 100
    burst_size: 20
```

## Performance Configuration

### Resource Limits

```yaml
performance:
  memory:
    max_heap_size: "2G"
    gc_threshold: 0.8
  cpu:
    max_threads: 10
    thread_pool_size: 20
  network:
    connection_timeout: 30
    read_timeout: 60
    write_timeout: 60
  caching:
    enabled: true
    max_size: 1000
    ttl: 3600
```

### Monitoring and Metrics

```yaml
metrics:
  enabled: true
  prometheus:
    enabled: true
    port: 9090
    path: "/metrics"
  health_checks:
    enabled: true
    interval: 30
    timeout: 5
  alerting:
    enabled: true
    webhook_url: "${ALERT_WEBHOOK_URL}"
```

## Troubleshooting

### Common Issues

1. **Missing Connector Class**: Ensure the Python class exists and is importable
2. **Invalid Configuration**: Check YAML syntax and required fields
3. **Missing Audio Files**: Verify audio files exist for local connector
4. **Network Issues**: Check API endpoints for remote connectors
5. **Permission Errors**: Verify file permissions for logs and certificates
6. **Environment Variables**: Ensure environment variables are properly set

### Debug Mode

Enable debug logging to see detailed configuration loading:

```yaml
logging:
  level: "DEBUG"
  handlers:
    - type: "console"
      level: "DEBUG"
    - type: "file"
      filename: "logs/config_debug.log"
      level: "DEBUG"
```

### Configuration Validation

```bash
# Validate configuration syntax
python -c "
import yaml
with open('config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)
print('Configuration is valid')
"

# Check for missing environment variables
python -c "
import os
import yaml
with open('config/config.yaml', 'r') as f:
    config = yaml.safe_load(f)
# Check for ${VARIABLE} patterns
"
```

## Best Practices

### Configuration Management

- **Version Control**: Keep configuration in version control
- **Environment Separation**: Use different configs for dev/staging/prod
- **Sensitive Data**: Use environment variables for secrets
- **Documentation**: Document all configuration options
- **Validation**: Implement configuration validation

### Security

- **Secret Management**: Use proper secret management systems
- **Access Control**: Limit access to configuration files
- **Encryption**: Encrypt sensitive configuration data
- **Audit Logging**: Log configuration changes

### Performance

- **Caching**: Cache configuration data appropriately
- **Lazy Loading**: Load configuration sections on demand
- **Validation**: Validate configuration early in startup
- **Monitoring**: Monitor configuration-related metrics

## License

This code is licensed under the [Cisco Sample Code License v1.1](../LICENSE). See the main project README for details. 