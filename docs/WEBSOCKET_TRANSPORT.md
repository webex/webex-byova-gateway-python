# BYOVA WebSocket Transport

The gateway can run the existing gRPC service, the Webex BYOVA WebSocket API,
or both listeners in one process. Both transports use the same configured
connectors, router, VAD behavior, handoff mapping, and monitoring process.

The WebSocket transport implements:

- `GET /v1/va`: one long-lived JSON text WebSocket per call
- `GET /v1/listVirtualAgents`: one request and response; the gateway leaves the
  socket open for the peer to close and applies a bounded idle timeout
- `SESSION_START`, caller audio, DTMF, input events, gateway VAD boundaries,
  provider output, transfer, and session termination
- strict concrete validation for call traffic plus forward-compatible discovery
  parsing that ignores unknown control-plane fields, matching Cisco's sample
- pre-upgrade JWT validation against the separate WebSocket datasource
- bounded input, output, and connector-worker capacity
- cancellation-safe worker accounting and one reserved cleanup worker, so a
  slow provider teardown does not block the socket event loop
- monotonic sender sequence validation, PING/PONG, fatal protocol errors, and
  exactly-once provider cleanup on disconnect

## Contract

The WebSocket interface is JSON/AsyncAPI, not a second protobuf service. A
pinned copy of the official schemas and the known upstream `allOf` composition
defect are in [`schemas/websocket`](../schemas/websocket/README.md).

The first `/v1/va` application message must be `VOICE_VA_REQUEST` containing a
`SESSION_START` event. The default deadline is 10 seconds. Every later client
envelope must use a strictly increasing `seq`; gaps are allowed. Binary frames,
unknown message types, malformed JSON, invalid lifecycle transitions, and
sustained queue pressure produce an `ERROR` and close the socket.

For a partner-initiated transfer or session end, the gateway sends the
terminal `VOICE_VA_RESPONSE`, flushes it, and waits for WxCC to close the
conversation socket. It does not close immediately after sending the terminal
event. A bounded peer-close timeout prevents an abandoned connection from
holding provider state indefinitely. A transfer or session end that a
connector delivers asynchronously, after the request that triggered it has
returned, enters the same terminal state.

On gateway shutdown, new upgrades receive HTTP 503, every active call is closed
with WebSocket code 1001, and each provider session is ended before the
listener stops. The drain is bounded (8 seconds by default).

The gateway owns VAD by default even though the socket is full duplex. A
connector may opt out through the existing speech-boundary capability, but the
gateway and provider must not both detect boundaries for one conversation.

## Local dual-protocol demo

Install the runtime requirements and generate the existing gRPC modules. The
complete development-only configuration is checked in as
[`config/websocket_local_example.yaml`](../config/websocket_local_example.yaml).
Its essential transport settings are:

```yaml
transports:
  mode: "both"
  allow_partial_transport_startup: false
  websocket:
    host: "127.0.0.1"
    port: 8765
    discovery_idle_timeout_seconds: 5
    allow_unauthenticated_local_dev: true

jwt_validation:
  enabled: false

websocket_jwt_validation:
  enabled: false

data_source:
  enabled: false

websocket_data_source:
  enabled: false
```

The authentication bypass is rejected for non-loopback clients. Never use it
for a shared, public, Webex-connected, or production endpoint.
For a WebSocket-only local example, use
[`config/websocket_only_example.yaml`](../config/websocket_only_example.yaml).
It does not create the gRPC server or read any gRPC datasource credentials.

Start the gateway:

```bash
source venv/bin/activate
GATEWAY_CONFIG=config/websocket_local_example.yaml python main.py
```

In another terminal, verify discovery and session start:

```bash
venv/bin/python tools/websocket_smoke.py \
  --url ws://127.0.0.1:58765 \
  --mode list
venv/bin/python tools/websocket_smoke.py \
  --url ws://127.0.0.1:58765 \
  --mode session \
  --agent-id "Local Audio: Local Playback"
```

## Webex-connected configuration

Configure independent profiles for the two datasource contracts:

```yaml
transports:
  mode: "both"
  websocket:
    allow_unauthenticated_local_dev: false

jwt_validation:
  enabled: true
  enforce_validation: true
  datasource_url: "https://gateway.example.com"
  datasource_schema_uuid: "5397013b-7920-4ffc-807c-e8a3e0a18f43"

websocket_jwt_validation:
  enabled: true
  datasource_url: "wss://gateway.example.com"
  datasource_schema_uuid: "a38a10b7-43e4-4676-a076-a7d6dce9387d"
```

`data_source` manages the gRPC registration and `websocket_data_source` manages
the WebSocket registration. Combined mode requires separate Service Apps,
datasource IDs, URLs, schemas, token providers, and JWT claim validation. The
organization administrator OAuth identity used to obtain Service App tokens
may be shared, but each transport must have its own Service App credentials.
Register the WebSocket datasource with the secure WebSocket origin without
`/v1/va`; the configured JWT URL must exactly match that value. Webex selects
the socket and discovery paths from the protocol contract. Public WSS/TLS
terminates at the AWS ALB while the Python process exposes separate private
listener ports.

Authorize the WebSocket-only Service App for schema
`a38a10b7-43e4-4676-a076-a7d6dce9387d`. Keep the existing gRPC Service App
authorized only for its gRPC schema.

For the controlled AWS test pattern, route `/v1/va` and
`/v1/listVirtualAgents` from the existing HTTPS listener to an HTTP/1.1 target
group on the WebSocket application port. Use `/health` only as that target
group's private process-health check. See
[AWS Test Deployment Considerations](AWS_TEST_DEPLOYMENT_CONSIDERATIONS.md).

## Provider audio modes

WebSocket discovery and `/v1/va` use the same transport eligibility check.
Connectors default to gRPC-only. Local Audio and GECX declare both gRPC and
WebSocket support; a deployment can restrict either connector with an explicit
`supported_transports` override. Other connectors require a reviewed opt-in.
A manually supplied agent ID cannot bypass this filter.

This eligibility is the WxCC-to-gateway transport, not the provider protocol.
`GECXConnector` talks to CES over gRPC even when it is exposed to WxCC through
WebSocket. Configure the separate `GECXWebSocketConnector` and use a distinct
agent ID when both the WxCC and CES connections should use WebSocket.

- GECX and Local Audio declare `raw_chunk`.
- `AWSLexConnector` remains gRPC-only. The separate `AWSLexWebSocketConnector`
  advertises only WebSocket and uses `wav_final`. Both share the same
  utterance-buffered Lex `RecognizeUtterance` implementation; the WebSocket
  adapter does not implement the provider's HTTP/2 `StartConversation` stream.
  Their discovery IDs use distinct `aws_lex_connector:` and
  `aws_lex_websocket_connector:` prefixes. See [Lex configuration](AWS_LEX_CONFIGURATION.md).
- Existing third-party connectors that do not declare the optional capability
  default to `raw_chunk`, preserving their source compatibility.

`raw_chunk` accepts raw provider chunks or strips the container from a complete
WAV and emits 100–65,536 byte `CHUNK` responses followed by an empty-audio
`FINAL`. `wav_final` emits one complete WAV response. Unsupported media that
would require general codec or sample-rate transcoding is rejected.

See [WebSocket Live Testing](WEBSOCKET_LIVE_TESTING.md) for the local readiness
checks, live acceptance matrix, and evidence to collect when resuming testing.
