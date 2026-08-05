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
  streaming_max_workers: 100
  request_queue_maxsize: 100
  response_queue_maxsize: 100
  max_terminal_playback_seconds: 30
```

`host` and `port` control the insecure application listener. Production deployments should
place it behind an approved TLS boundary or add an appropriate secure listener. See
[Security Configuration](../docs/Security-Configuration.md).

`streaming_max_workers` sizes the method-specific executor for long-lived caller streams.
`request_queue_maxsize` and `response_queue_maxsize` bound the number of protobuf messages
buffered per stream while caller ingestion, ordered connector processing, and WxCC response
delivery run independently. Both queue sizes must be greater than zero. The queues bound
memory and apply backpressure; they are not production throughput targets.

`max_terminal_playback_seconds` is a safety ceiling for legacy complete-WAV
announcement responses. GECX raw CHUNK streaming does not use this delay.
Maximum gRPC message sizes and the concurrent-stream option remain set in `main.py`.

## Voice Activity Detection

```yaml
voice_activity_detection:
  threshold: 0.5
  start_debounce_ms: 96
  end_silence_ms: 1000
  fallback_sample_rate_hertz: 8000
```

These values configure the gateway's speech-boundary observer for each conversation.
`fallback_sample_rate_hertz` is used only when WxCC omits the input sample rate. Changes to
the threshold or timing values affect turn boundaries and caller experience, so validate
them with representative audio and latency tests before deployment.

## Connectors

Connectors are keyed dictionaries:

```yaml
connectors:
  local_audio_connector:
    type: "local_audio_connector"
    class: "LocalAudioConnector"
    module: "connectors.local_audio_connector"
    config:
      agent_id: "Local Playback"
      audio_base_path: "audio"
```

The loader requires each connector to provide `class` and `module`; an omitted `config`
mapping defaults to an empty dictionary. It dynamically imports `src.<module>`, verifies
that the class implements `IVendorConnector`, and registers the agents returned by the
connector.

Available connector documentation:

- [Connector interface and development](../src/connectors/README.md)
- [Local audio configuration](../docs/LOCAL_AUDIO_CONFIGURATION.md)
- [AWS Lex configuration](../docs/AWS_LEX_CONFIGURATION.md)
- [Google CX Agent Studio configuration](../docs/guides/byova-gecx-setup.md)
- `config/aws_lex_example.yaml`
- `config/gecx_example.yaml`
- `config/config.cloudrun.yaml`

### Local Audio Connector

The checked-in configuration maps response types to the audio files included in `audio/`:

```yaml
connectors:
  local_audio_connector:
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

Use `agent_id`, not an `agents` list, to change the advertised local agent name. See
[Local Audio Connector Configuration](../docs/LOCAL_AUDIO_CONFIGURATION.md) for the local
and end-to-end sandbox test paths.

### GECX / CX Agent Studio Connector

The GECX connector streams WxCC caller audio to Google CX Agent Studio through the CES
`BidiRunSession` API. CES 8 kHz mu-law output frames are forwarded immediately
as raw BYOVA `CHUNK` responses, followed by exactly one normal or terminal
`FINAL`.

```yaml
connectors:
  gecx_connector:
    type: "gecx_connector"
    class: "GECXConnector"
    module: "connectors.gecx_connector"
    config:
      project_id: "YOUR_PROJECT_ID"
      location: "us"
      application_id: "YOUR_APPLICATION_ID"
      language_code: "en-US"
      input_sample_rate_hertz: 8000
      input_audio_encoding: "MULAW"
      output_sample_rate_hertz: 8000
      output_audio_encoding: "MULAW"
      suppress_long_leading_audio: true
      output_leading_audio_min_ms: 5000
      output_speech_rms_threshold: 200
      output_speech_start_frames: 2
      output_speech_preroll_ms: 100
      # Keep GECX prompt interruption disabled while barge-in is under review.
      barge_in_enabled: false
      force_input_format: "wxcc"
      turn_response_timeout_seconds: 30
      # Trailing codec silence for reliable CES audio endpoint detection.
      endpointing_silence_ms: 2000
      input_preroll_ms: 500
      input_pause_preroll_ms: 250
      terminal_response_grace_seconds: 3
      # Omit auth settings to use Application Default Credentials.
      # service_account_key: "/path/to/service-account.json"
      agents:
        - "My GECX Agent"
```

GECX CHUNK output currently requires `output_sample_rate_hertz: 8000` and
`output_audio_encoding: "MULAW"`. Unsupported output combinations fail during
connector initialization; broader output formats are not silently mislabeled.
The leading-audio guard activates only when the first CES frame is at least
`output_leading_audio_min_ms` and contains no sustained speech. It then retains
`output_speech_preroll_ms` before the first detected speech frames.
When the gateway detects caller speech, it also isolates the next response turn
until CES sends a recognition result. An interruption signal alone does not
open the gate because CES can send the stale turn completion immediately after
that signal. Any autonomous no-input prompt that overlaps the caller turn is
suppressed, allowing the post-input CES answer to remain attached to the active
WxCC response stream. Outside a caller-owned turn, autonomous CES prompt audio
is pushed directly to the active WxCC stream instead of waiting for another
caller frame to drain it. Those autonomous chunks set
`is_barge_in_enabled` from the `barge_in_enabled` connector setting, which
defaults to `false`; caller-triggered and greeting chunks always remain false.

See [`gecx_example.yaml`](gecx_example.yaml) for all options and the
[GECX Setup Guide](../docs/guides/byova-gecx-setup.md) for IAM, deployment, and
Webex Contact Center configuration.

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

## BYODS Datasource Lifecycle

The optional `data_source` section uses `webex-byods-sdk` to discover or register the
gateway datasource before the gRPC listener starts and renew its JWS before expiry:

```yaml
data_source:
  enabled: true
  fail_startup_on_error: true
  id: ""
  id_env: "WEBEX_BYODS_DATA_SOURCE_ID"
  # Empty values inherit the JWT validation URL and schema.
  url: ""
  schema_id: ""
  audience: "BYOVAGateway"
  subject: "callAudioData"
  token_lifetime_minutes: 1440
  renewal_lead_time_minutes: 60
  retry_interval_seconds: 60
  auth:
    type: "oauth_refresh"
    client_id_env: "WEBEX_BYODS_CLIENT_ID"
    client_secret_env: "WEBEX_BYODS_CLIENT_SECRET"
    refresh_token_env: "WEBEX_BYODS_REFRESH_TOKEN"
```

Values ending in `_env` name environment variables; they do not contain credentials. The
Service App needs `spark-admin:datasource_read` and `spark-admin:datasource_write`.

When neither `id` nor the variable named by `id_env` supplies an ID, startup searches for a
matching URL, schema, audience, and subject. It registers only when no match exists and
rejects ambiguous matches. Explicit `url` and `schema_id` values must match the corresponding
`jwt_validation` settings.

For short-lived development, use `auth.type: "static"` with
`access_token_env: "WEBEX_BYODS_ACCESS_TOKEN"`. Static access tokens cannot be refreshed;
use OAuth refresh credentials for unattended operation.

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
- [Local audio configuration](../docs/LOCAL_AUDIO_CONFIGURATION.md)
- [BYODS datasource lifecycle](#byods-datasource-lifecycle)
- [GECX setup](../docs/guides/byova-gecx-setup.md)
- [JWT authentication](../docs/JWT_AUTHENTICATION.md)
- [Testing](../docs/TESTING.md)
- [Return to the project README](../README.md)
