# Gateway Configuration

`config/config.yaml` is the configuration file loaded by `main.py`. This reference documents
the settings used by the current sample implementation. Connector-specific options are
documented with their connectors.

The gateway does not perform general `${ENV_VAR}` substitution inside YAML. Environment
variables are used directly by specific components, including Webex OAuth and the standard
AWS credential chain.

## Gateway Listener

```yaml
gateway:
  host: "0.0.0.0"
  port: 50051
```

`host` and `port` control the insecure application listener. Production deployments should
place it behind an approved TLS boundary or add an appropriate secure listener. See
[Security Configuration](../docs/Security-Configuration.md).

The gRPC worker count, maximum message sizes, and concurrent-stream option are currently set
in `main.py`; values elsewhere in YAML are not production capacity controls.

## Connectors

Connectors are keyed dictionaries:

```yaml
connectors:
  local_audio_connector:
    type: "local_audio_connector"
    class: "LocalAudioConnector"
    module: "connectors.local_audio_connector"
    config:
      agents:
        - "Local Playback"
```

The loader requires each connector to provide `class` and `module`; an omitted `config`
mapping defaults to an empty dictionary. It dynamically imports `src.<module>`, verifies
that the class implements `IVendorConnector`, and registers the agents returned by the
connector.

Available connector documentation:

- [Connector interface and development](../src/connectors/README.md)
- [AWS Lex configuration](../docs/AWS_LEX_CONFIGURATION.md)
- `config/aws_lex_example.yaml`

### Local Audio Connector

The checked-in configuration maps response types to the audio files included in `audio/`:

```yaml
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

### AWS Credentials

The AWS Lex connector uses the standard AWS SDK credential chain. Prefer workload roles or
short-lived credentials. For local development, supported SDK sources include environment
variables, AWS shared configuration, and AWS SSO.

Do not put production access keys in `config.yaml`.

## Monitoring Server

```yaml
monitoring:
  enabled: true
  host: "0.0.0.0"
  port: 8080
  debug: false
```

`enabled`, `host`, `port`, and `debug` control the Flask monitoring server started by
`main.py`. The checked-in YAML also contains `metrics_enabled` and
`health_check_interval`, but the current sample does not expose an instrumented production
metrics endpoint or schedule health checks from those values.

See [Monitoring Interface](../src/monitoring/README.md).

## Monitoring Dashboard Authentication

```yaml
authentication:
  enabled: true
  environment: "dev"
  session:
    timeout_hours: 24
    secret_key_env: "FLASK_SECRET_KEY"
  webex_oauth:
    scopes: "openid email profile"
    state: "byova_gateway_auth"
```

When enabled, the monitoring application reads:

- `FLASK_SECRET_KEY`, or the environment variable named by `secret_key_env`
- `WEBEX_CLIENT_ID`
- `WEBEX_CLIENT_SECRET`
- `WEBEX_REDIRECT_URI`
- `AUTHORIZED_WEBEX_ORG_IDS`

See [Authentication Quick Start](../AUTHENTICATION_QUICKSTART.md). This authentication is
separate from JWT validation on the gRPC data plane.

## gRPC JWT Validation

```yaml
jwt_validation:
  enabled: true
  enforce_validation: true
  datasource_url: "https://your-gateway.example.com:443"
  datasource_schema_uuid: "5397013b-7920-4ffc-807c-e8a3e0a18f43"
  cache_duration_minutes: 60
```

When enabled, `datasource_url` is required and must exactly match the registered data-source
URL. The gateway will not start with an empty value.

See [gRPC JWT Authentication](../docs/JWT_AUTHENTICATION.md) for claims, issuers, deployment
modes, and troubleshooting.

## Logging

```yaml
logging:
  gateway:
    level: "INFO"
    format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file: "logs/gateway.log"
  web:
    level: "WARNING"
    format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file: "logs/web.log"
```

The current logging setup uses the configured level, format, and file. Although the sample
YAML contains `max_size` and `backup_count`, `main.py` currently uses a plain `FileHandler`,
so those values do not rotate files.

Production services should use structured, centralized logging as described in
[Production Readiness](../docs/PRODUCTION_READINESS.md).

## Sample Placeholder Sections

The checked-in YAML includes top-level `sessions` and `audio.supported_formats` sections.
They describe intended sample settings, but `main.py` and `WxCCGatewayServer` do not currently
enforce those values as session, concurrency, cleanup, or codec limits. Do not use them for
capacity planning or production safety controls.

Connector-level audio settings, such as AWS Lex `audio_logging` and `audio_buffering`, are
read by the relevant connector implementation.

## Local Development Settings

For a local-only run that is not connected to Webex:

```yaml
authentication:
  enabled: false

jwt_validation:
  enabled: false
```

Do not use disabled authentication for a public or production endpoint. See
[Local Development](../docs/LOCAL_DEVELOPMENT.md).

## Validation and Troubleshooting

At startup, the application validates YAML parsing, connector `class` and `module` fields,
and the required datasource URL when JWT validation is enabled. Individual connectors may
perform additional validation.

Common checks:

- Confirm YAML indentation and mapping structure.
- Confirm connector module paths are relative to `src/`.
- Confirm configured audio files exist under `audio/`.
- Confirm AWS credentials and region through the standard AWS SDK chain.
- Confirm the datasource URL exactly matches the registered value.
- Review `logs/gateway.log` and standard output for startup failures.

## Related Documentation

- [Local development](../docs/LOCAL_DEVELOPMENT.md)
- [JWT authentication](../docs/JWT_AUTHENTICATION.md)
- [Testing](../docs/TESTING.md)
- [Return to the project README](../README.md)
