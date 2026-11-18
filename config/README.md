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

## Transport Listeners

```yaml
transports:
  mode: "grpc" # grpc | websocket | both
  allow_partial_transport_startup: false
  websocket:
    host: "0.0.0.0"
    port: 8765
    first_message_timeout_seconds: 10
    discovery_idle_timeout_seconds: 5
    terminal_flush_timeout_seconds: 2
    terminal_peer_close_timeout_seconds: 30
    queue_maxsize: 100
    queue_put_timeout_seconds: 1
    max_message_bytes: 131072
    connector_max_workers: 20
    connector_max_pending: 20
    output_chunk_bytes: 3200
    allow_unauthenticated_local_dev: false
```

If `transports` is absent, the gateway remains gRPC-only. `grpc` and
`websocket` require only their selected transport's authentication and
datasource configuration. `both` starts the listeners in one process with a
shared router and conversation registry, while keeping their Service Apps,
datasources, JWT profiles, and renewal workers independent. Partial startup
requires the explicit development override and applies only to `both` mode.

`discovery_idle_timeout_seconds` bounds how long the server waits for the WxCC
control-plane peer to close after receiving the virtual-agent list. The server
does not immediately close the discovery socket after sending the response.

After sending `TRANSFER_TO_AGENT` or server-initiated `SESSION_END`, the
gateway flushes the terminal response and leaves the conversation socket open
for the WxCC peer to close, as required by the WebSocket lifecycle. The
`terminal_peer_close_timeout_seconds` safety bound closes an unresponsive peer
after 30 seconds by default.

The local authentication bypass is accepted only from a loopback peer. Public
and Webex-connected WebSockets require the independent
`websocket_jwt_validation` profile. See
[BYOVA WebSocket Transport](../docs/WEBSOCKET_TRANSPORT.md).

## Voice Activity Detection

```yaml
voice_activity_detection:
  threshold: 0.5
  start_debounce_ms: 96
  end_silence_ms: 1000
  speech_end_grace_ms: 1000
  recognition_assisted_endpointing_enabled: false
  recognition_assisted_grace_ms: 200
  fallback_sample_rate_hertz: 8000
```

These values configure the gateway's speech-boundary observer for each conversation.
`fallback_sample_rate_hertz` is used only when WxCC omits the input sample rate. Changes to
the threshold or timing values affect turn boundaries and caller experience, so validate
them with representative audio and latency tests before deployment.

For streaming connectors that merge natural pauses, `speech_end_grace_ms` is the
cancellable delay after local VAD first reports speech ended. Optional
recognition-assisted endpointing does not replace local VAD and does not batch audio: it
uses a current-turn vendor recognition result only to shorten that post-VAD delay to
`recognition_assisted_grace_ms`. If recognition is absent, the full speech-end grace is
retained. If speech resumes during either delay, the pending endpoint is cancelled and the
resumed audio remains in the same input turn. The optimization is disabled by default.

## Connectors

Connectors are keyed dictionaries:

```yaml
connectors:
  local_audio_connector:
    type: "local_audio_connector"
    class: "LocalAudioConnector"
    module: "connectors.local_audio_connector"
    supported_transports: ["grpc", "websocket"]
    config:
      agent_id: "Local Playback"
      audio_base_path: "audio"
```

The loader requires each connector to provide `class` and `module`; an omitted `config`
mapping defaults to an empty dictionary. It dynamically imports `src.<module>`, verifies
that the class implements `IVendorConnector`, and registers the agents returned by the
connector.

`supported_transports` accepts only `grpc` and `websocket`. When it is omitted,
the connector's declared safe default is used; the base connector default is
gRPC-only, while Local Audio and GECX declare both. The router applies this
eligibility to both agent discovery and runtime lookup. A deployment can still
restrict either connector to one transport with an explicit override.

For GECX, this setting is independent of the provider connection. Use
`GECXConnector` for CES gRPC or `GECXWebSocketConnector` for native CES
WebSocket. When both are loaded, give them distinct agent IDs and explicitly
restrict each connector so discovery identifies the intended provider path.

Available connector documentation:

- [Connector interface and development](../src/connectors/README.md)
- [Local audio configuration](../docs/LOCAL_AUDIO_CONFIGURATION.md)
- [AWS Lex configuration](../docs/AWS_LEX_CONFIGURATION.md)
- [Google CX Agent Studio configuration](../docs/guides/byova-gecx-setup.md)
- `config/aws_lex_example.yaml`
- `config/gecx_example.yaml`
- `config/gecx_websocket_example.yaml`
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

### GECX / CX Agent Studio Connectors

The GECX connectors stream WxCC caller audio to Google CX Agent Studio through the CES
`BidiRunSession` API. It can request 24 kHz Linear16 output and perform the final
anti-aliased 8 kHz mu-law conversion locally, or forward CES 8 kHz mu-law output
directly. Both paths emit immediate BYOVA `CHUNK` responses followed by exactly
one normal or terminal `FINAL`.

`GECXConnector` uses CES gRPC. `GECXWebSocketConnector` is a separate module
that uses the native CES JSON WebSocket endpoint with the same session behavior.

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
      # Recommended quality path. Use 8000/MULAW instead to compare direct CES
      # mu-law output without connector-side conversion.
      output_sample_rate_hertz: 24000
      output_audio_encoding: "LINEAR16"
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
      input_holdback_ms: 250
      input_pause_preroll_ms: 250
      input_stream_chunk_ms: 100
      input_queue_max_chunks: 20
      input_queue_put_timeout_ms: 50
      terminal_response_grace_seconds: 3
      # Omit auth settings to use Application Default Credentials.
      # service_account_key: "/path/to/service-account.json"
      # oauth_client_id: "..."
      # oauth_client_secret: "..."
      # oauth_token_file: "gecx_oauth_token.json"
      agents:
        - "My GECX Agent"
```

`terminal_response_grace_seconds` prevents a late CES `EndSession` from
following an already-committed normal `FINAL`. The connector applies the grace
window after terminal-sounding output and after a completed turn with no audio
or text, since native CES WebSocket sessions can send the terminal event just
after an empty turn-complete signal.

GECX accepts two explicit provider-output pairs: `24000`/`LINEAR16` for the
recommended connector-side conversion path, or `8000`/`MULAW` for direct CES
mu-law. WxCC always receives 8 kHz mu-law; unsupported provider-output pairs
fail during connector initialization rather than being silently mislabeled.
The leading-audio guard activates only when the first CES frame is at least
`output_leading_audio_min_ms` and contains no sustained speech. It then retains
`output_speech_preroll_ms` before the first detected speech frames.
Caller input follows a separate progressive path: bounded pre-roll is flushed
at speech start, active normalized audio is queued as it arrives, and only the
configured `input_holdback_ms` tail waits for a committed speech end. The CES
input queue is bounded; sustained backpressure ends the session explicitly
instead of accumulating latency or silently dropping caller audio.
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
Interactive OAuth credentials are stored as authorized-user JSON, written
atomically with owner-only permissions. Do not reuse the former pickle token
format; delete any old `gecx_oauth_token.pickle` file and authenticate again.

See [`gecx_example.yaml`](gecx_example.yaml) for the gRPC provider variant,
[`gecx_websocket_example.yaml`](gecx_websocket_example.yaml) for native CES
WebSocket, and the
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

## WebSocket JWT Validation

```yaml
websocket_jwt_validation:
  enabled: true
  datasource_url: "wss://your-gateway.example.com"
  datasource_schema_uuid: "a38a10b7-43e4-4676-a076-a7d6dce9387d"
  cache_duration_minutes: 60
```

Authentication completes before the HTTP connection upgrades. The WebSocket
and gRPC validators share fetched JWKS keys but validate their own datasource
URL and schema claims.
The WebSocket datasource URL is the secure WebSocket origin without the
`/v1/va` path. Use the exact URL accepted at registration in the JWT profile
too. With an AWS ALB, route `/v1/va` and
`/v1/listVirtualAgents` to the private WebSocket listener on port 8765.

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

`websocket_data_source` has the same lifecycle fields but uses its own ID, URL,
WebSocket schema, and WebSocket-only Service App. It falls back to
`websocket_jwt_validation` values rather than the gRPC profile. In `both` mode,
the gateway rejects identical credential mappings, datasource IDs, or datasource
ID environment-variable names. The organization administrator OAuth bootstrap
identity may be shared, but the two Service App identities may not be shared.
Each lifecycle creates and renews its own token provider.

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
