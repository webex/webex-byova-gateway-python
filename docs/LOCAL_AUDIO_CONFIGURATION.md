# Local Audio Connector Configuration

The local audio connector lets you validate a Webex Contact Center BYOVA setup
before choosing or provisioning a voice-agent provider. It uses audio files from
this repository, so it does not require AWS credentials, a vendor account, speech
recognition, or text-to-speech services.

This is a good first connector when you already have a Webex Contact Center
sandbox and want to prove that the gateway, BYODS registration, virtual-agent
discovery, Flow Designer configuration, audio playback, DTMF handling, and agent
transfer path work together.

> **Functional example only:** The local audio connector is a deterministic test
> fixture, not a conversational voice agent or a production implementation.

## What the Connector Does

During a call, the connector follows this fixed behavior:

| Caller action | Connector behavior |
| --- | --- |
| Call enters the Virtual Agent V2 activity | Plays `welcome.wav` |
| Caller speaks | Accepts the audio but does not interpret or answer it |
| Caller presses **5** | Plays `transferring.wav` and sends an agent-transfer event |
| Caller presses **6** | Plays `goodbye.wav` and sends a conversation-end event |
| Caller presses another key | Continues waiting for input without a response |

The connector disables barge-in for its prerecorded prompts. It can optionally
record caller audio for development diagnostics.

## Prerequisites

For a local gateway smoke test, you need:

- Python 3.8 or later
- Git
- This repository cloned locally

For an end-to-end sandbox call, you also need:

- A Webex Contact Center sandbox or organization with BYOVA enabled
- Contact Center administrator access
- A Webex Service App authorized by the sandbox organization
- Service App credentials with `spark-admin:datasource_read` and
  `spark-admin:datasource_write` when using automatic datasource registration
- A publicly reachable HTTPS endpoint that supports HTTP/2 gRPC and routes to
  gateway port `50051`
- A test entry point and a published flow containing a Virtual Agent V2 activity

The Webex-side prerequisites are the same for any vendor connector. The local
connector simply removes the vendor-specific account and bot setup from the
first test.

## Configuration Options

### Optional

- **`agent_id`**: Display name for the local agent (default: `Local Playback`)
- **`audio_base_path`**: Directory containing prompt files (default: `audio`)
- **`audio_files`**: File names for the supported prompt roles
- **`record_caller_audio`**: Save caller audio for diagnostics (default: `false`)
- **`audio_recording.output_dir`**: Destination for caller recordings (default:
  `logs`)

The advertised virtual-agent ID includes the connector prefix. With the default
configuration, Flow Designer discovers:

```text
Local Audio: Local Playback
```

Use `agent_id`, not an `agents` list, to change the name.

## Example Configuration

Add or update this entry under `connectors` in `config/config.yaml`:

```yaml
connectors:
  local_audio_connector:
    type: "local_audio_connector"
    class: "LocalAudioConnector"
    module: "connectors.local_audio_connector"
    config:
      agent_id: "Local Playback"
      audio_base_path: "audio"
      record_caller_audio: false
      audio_files:
        welcome: "welcome.wav"
        transfer: "transferring.wav"
        goodbye: "goodbye.wav"
        error: "error.wav"
        default: "default_response.wav"
```

The current scripted call path actively plays the `welcome`, `transfer`, and
`goodbye` files. The `error` and `default` mappings are available for extending
the example but are not played during its normal DTMF-driven flow.

You can remove other connector entries while evaluating the local connector.
This avoids unrelated vendor credential or discovery errors in the startup logs.

## Audio Files

The repository includes working prompt files in `audio/`. To replace them:

1. Add each file below `audio/`, or below your configured `audio_base_path`.
2. Keep the files as mono PCM WAV audio. The bundled converter supports the
   sample rates used by the examples and converts them to the 8 kHz, 8-bit
   mu-law WAV output required by Webex Contact Center.
3. Update `audio_files` if you changed any file names.
4. Restart the gateway after changing the configuration.

Run the gateway from the repository root so a relative path such as `audio`
resolves to the expected directory. A misspelled directory or file name can
result in an empty prompt; check `logs/gateway.log` for `File not found` or audio
conversion errors.

For more detail, see the [Audio Files Guide](../audio/README.md).

## Test the Connector Locally

This smoke test confirms that the gateway loads the connector and advertises the
expected virtual-agent ID. It does not place a Contact Center call.

### 1. Set up the gateway

From the repository root:

```bash
python -m venv venv

# macOS or Linux
source venv/bin/activate

# Windows PowerShell
# venv\Scripts\Activate.ps1

pip install -r requirements.txt
python -m grpc_tools.protoc \
  -I./proto \
  --python_out=src/generated \
  --grpc_python_out=src/generated \
  proto/*.proto
```

### 2. Temporarily disable JWT validation

For a localhost-only smoke test, update `config/config.yaml`:

```yaml
jwt_validation:
  enabled: false
```

Do not use this setting when Webex Contact Center connects to the gateway. The
end-to-end path below requires JWT validation.

### 3. Start and verify the gateway

```bash
python main.py
```

In a second terminal, verify the health and loaded connector:

```bash
curl http://localhost:8080/health
curl http://localhost:8080/api/config
```

The configuration response should include `local_audio_connector` and the agent
`Local Audio: Local Playback` (or your customized name). The monitoring dashboard
is available at `http://localhost:8080`; dashboard login requires the Webex OAuth
settings described in the
[Authentication Quick Start](../AUTHENTICATION_QUICKSTART.md), but the two API
checks above do not require dashboard login.

## Connect the Sandbox End to End

Once the local smoke test passes, use the same Webex setup that a real voice-agent
connector will use.

### 1. Expose the gRPC endpoint over HTTPS

Deploy the gateway behind a public endpoint with a valid TLS certificate and
HTTP/2 gRPC routing to port `50051`. Keep the monitoring interface on port `8080`
protected separately; BYODS registers the gRPC endpoint, not the dashboard.

See [Security Configuration](Security-Configuration.md#grpc-tls-termination-setup)
for an AWS load-balancer example. The gateway is sample code, so review the
deployment and security controls before exposing it.

### 2. Enable JWT validation

Set the public endpoint in `config/config.yaml`:

```yaml
jwt_validation:
  enabled: true
  enforce_validation: true
  datasource_url: "https://byova-gateway.example.com"
  datasource_schema_uuid: "5397013b-7920-4ffc-807c-e8a3e0a18f43"
  cache_duration_minutes: 60
```

The `datasource_url` must exactly match the URL used in the BYODS registration,
including scheme, hostname, path, and any explicitly supplied port. Restart the
gateway after changing it.

### 3. Enable automatic BYOVA data-source registration

Follow the Webex
[Bring Your Own Virtual Agent](https://developer.webex.com/webex-contact-center/docs/bring-your-own-virtual-agent)
and
[Bring Your Own Data Source](https://developer.webex.com/webex-contact-center/docs/bring-your-own-data-source-cc)
guides to confirm BYOVA is enabled, create a Service App with the required
data-source scopes and allowed gateway domain, and have a sandbox administrator
authorize it.

Provide the authorized OAuth credentials through environment variables:

```bash
export WEBEX_BYODS_CLIENT_ID="your-client-id"
export WEBEX_BYODS_CLIENT_SECRET="your-client-secret"
export WEBEX_BYODS_REFRESH_TOKEN="your-refresh-token"
```

Do not commit these values. Use your deployment platform's secret manager for
shared or long-running environments.

Enable lifecycle management in `config/config.yaml`:

```yaml
data_source:
  enabled: true
  fail_startup_on_error: true
  id: ""
  id_env: "WEBEX_BYODS_DATA_SOURCE_ID"
  # Empty values inherit jwt_validation.datasource_url and schema.
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

Start the gateway after the public endpoint is available. Before accepting gRPC
traffic, it searches for an exact URL, schema, audience, and subject match. It
reuses and reconciles one match or registers a new datasource when no match
exists. The startup summary prints the datasource ID and JWS expiry:

```text
BYODS Datasource:
   • Management: ENABLED
   • ID: <data-source-id>
   • Token Expires: <timestamp>
```

Keep the gateway running. It renews the JWS 60 minutes before expiry by default
and retries a failed renewal every 60 seconds. If more than one existing
datasource matches, set `WEBEX_BYODS_DATA_SOURCE_ID` to the intended ID and
restart.

For a one-time manual registration instead, leave `data_source.enabled` set to
`false`, register the same URL and BYOVA schema through the Webex API, and save
the returned datasource ID. Automatic renewal is disabled in that mode.

No vendor credentials are needed for the local connector.

### 4. Create the Contact Center virtual-agent feature

In Control Hub:

1. Go to **Contact Center > Integrations > Features**.
2. Create a virtual-agent feature using the authorized Service App.
3. Use the datasource ID printed by gateway startup as the resource identifier.
4. Give it a recognizable name such as `BYOVA Local Audio Test`.

### 5. Configure and publish the flow

The repository includes `BYOVA_Gateway_Flow.json` as a starting point.

1. Import the file into Flow Designer, or add a Virtual Agent V2 activity to an
   existing test flow.
2. Open the Virtual Agent V2 activity and reselect the virtual-agent feature you
   created. Do not rely on the connector identifier stored in the sample flow.
3. Select `Local Audio: Local Playback` as the virtual-agent ID. If it is not
   listed, use the troubleshooting steps below before continuing.
4. Confirm the activity's escalated branch routes to a test queue if you want to
   verify DTMF 5 transfer.
5. Validate, publish, and assign the flow to a sandbox test entry point.

### 6. Place a test call

Call the sandbox entry point and verify:

1. You hear the welcome prompt.
2. Speaking does not produce a reply; this is expected for the local connector.
3. Pressing **5** plays the transfer prompt and follows the activity's escalated
   path. Have a test agent signed in and available if the path routes to a queue.
4. On a separate call, pressing **6** plays the goodbye prompt and follows the
   handled/conversation-end path.
5. The gateway dashboard, `logs/gateway.log`, or `/api/connections` shows the call
   lifecycle.

At this point you have validated the vendor-neutral BYOVA plumbing. When you pick
a voice-agent provider, add its connector configuration, confirm its advertised
agent ID, and update the Virtual Agent V2 selection; the Service App, data-source,
public endpoint, and surrounding flow can usually remain in place if their URL
and schema requirements do not change.

## Optional Caller Audio Recording

To confirm that caller audio reaches the connector, enable development recording:

```yaml
connectors:
  local_audio_connector:
    type: "local_audio_connector"
    class: "LocalAudioConnector"
    module: "connectors.local_audio_connector"
    config:
      agent_id: "Local Playback"
      audio_base_path: "audio"
      record_caller_audio: true
      audio_recording:
        output_dir: "logs/local_audio_recordings"
```

Recordings may contain customer audio and personal data. Use only test calls,
restrict access to the output directory, define retention, and turn recording off
when the diagnostic is complete.

## Troubleshooting

### Gateway fails with `datasource_url is not configured`

JWT validation is enabled without a URL. For a localhost-only smoke test, set
`jwt_validation.enabled` to `false`. For a sandbox call, configure the exact
public BYODS URL and leave validation enabled.

### Automatic datasource registration fails during startup

- Confirm the three `WEBEX_BYODS_*` environment variables are available to the
  gateway process.
- Confirm the authorized Service App has both datasource read and write scopes.
- Confirm the public URL uses a domain allowed by the Service App.
- If the logs report multiple matches, set `WEBEX_BYODS_DATA_SOURCE_ID` to the
  intended datasource ID.
- Keep `fail_startup_on_error: true` for end-to-end testing so the gateway does
  not accept traffic without a managed datasource.

### The local agent does not appear in Flow Designer

- Confirm `/api/config` lists `Local Audio: Local Playback`.
- Confirm the public gRPC endpoint is reachable over HTTP/2 and reports `SERVING`.
- Confirm the Service App is authorized and the data source is active.
- Confirm the data-source URL exactly matches `jwt_validation.datasource_url`.
- Reopen or refresh the Virtual Agent V2 activity after fixing discovery.

### The call connects but the welcome prompt is silent

- Run the gateway from the repository root.
- Confirm the configured file exists below `audio_base_path`.
- Use a mono PCM WAV file.
- Search `logs/gateway.log` for file or conversion errors.

### Speech gets no response

This is expected. The local connector does not perform speech recognition or
generate conversational responses. Use DTMF 5 and 6 to exercise its scripted
branches.

### DTMF 5 does not reach an agent

The connector only emits the transfer event. Flow Designer must route the
Virtual Agent V2 activity's escalated branch to a queue, and a test agent must be
signed in and available to receive the call.

## Next Step: Choose a Voice-Agent Connector

After the local end-to-end test passes, compare or implement connectors using the
[Connectors Overview](../src/connectors/README.md). If you choose Amazon Lex, use
the [AWS Lex Connector Configuration](AWS_LEX_CONFIGURATION.md) guide for the
vendor-specific setup.
