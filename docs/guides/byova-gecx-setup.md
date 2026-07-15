# BYOVA + Google CX Agent Studio (GECX) Setup Guide

This guide explains how to connect Webex Contact Center (WxCC) BYOVA to an agent built in **CX Agent Studio** (Gemini Enterprise for Customer Experience) using the `GECXConnector` and the CES **BidiRunSession** API.

## Architecture

```
Caller -> WxCC -> BYOVA Gateway (gRPC) -> GECXConnector -> CES BidiRunSession -> CX Agent Studio
```

The connector sends WxCC caller audio to Google as it arrives. Its current
output mode buffers each CES agent turn and returns one WAV `FINAL` response;
BYOVA `CHUNK` output streaming is planned separately.

## Prerequisites

- WxCC sandbox or tenant with BYOVA entitlements
- GCP project with **CX Agent Studio** access
- CES API enabled and a CX Agent Studio application with API access
- Python 3.10+ and this gateway repository

## 1. Google Cloud and CX Agent Studio

### Enable APIs and IAM

1. Enable the Gemini Enterprise for Customer Experience / CES API in your GCP project.
2. Create a service account with role **`roles/ces.client`**.
3. Download a JSON key (development) or configure Application Default Credentials.

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:YOUR_SA@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/ces.client"
```

### Identify your app (deployment is optional)

1. Open [CX Agent Studio](https://ces.cloud.google.com) and open your agent app.
2. The app URL contains everything you need:

```
https://ces.cloud.google.com/projects/PROJECT_ID/locations/REGION/apps/APPLICATION_ID
```

3. `project_id`, `location`, and `application_id` are all you need. A published
   **deployment is optional** — if you omit `deployment_id`, the connector runs
   sessions against the app's **root (draft) agent**, which is convenient for
   testing and iterating. Provide `deployment_id` only to pin to a specific
   published version.

> Endpoint note: the streaming `BidiRunSession` RPC is served from the
> **regional** CES runtime endpoint `ces.<location>.rep.googleapis.com`
> (e.g. `ces.us.rep.googleapis.com`), not the global `ces.googleapis.com`. The
> connector derives this automatically from `location`; override with
> `api_endpoint` if required.

## 2. Gateway configuration

### Install dependencies

```bash
python -m venv venv
source venv/bin/activate     # macOS/Linux
# venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

### Configure the connector

Add a block to [`config/config.yaml`](../../config/config.yaml) (see [`config/gecx_example.yaml`](../../config/gecx_example.yaml)):

```yaml
gecx_connector:
  type: "gecx_connector"
  class: "GECXConnector"
  module: "connectors.gecx_connector"
  config:
    project_id: "YOUR_PROJECT_ID"
    location: "us"
    application_id: "YOUR_APPLICATION_ID"
    # deployment_id: "YOUR_DEPLOYMENT_ID"   # optional; omit for root/draft agent
    language_code: "en-US"
    input_sample_rate_hertz: 8000
    input_audio_encoding: "MULAW"
    output_sample_rate_hertz: 8000
    output_audio_encoding: "MULAW"
    initial_message: "Hello"
    enable_partial_responses: true
    force_input_format: "wxcc"
    turn_response_timeout_seconds: 30
    # Omit auth entirely to use Application Default Credentials (recommended on
    # Google Cloud; the runtime service account needs roles/ces.client).
    # service_account_key: "C:/path/to/ces-service-account.json"
    agents:
      - "My GECX Agent"
```

The `agents` list entry is the name WxCC uses when selecting a virtual agent in `ListVirtualAgents`.

For local-only testing, either configure `jwt_validation.datasource_url` for
your registered datasource or temporarily set `jwt_validation.enabled: false`.
Keep JWT validation enabled for a shared or public gateway.

### Run the gateway

```bash
python main.py
```

Open `http://localhost:8080` and confirm **My GECX Agent** appears in the dashboard.

## 3. Webex Contact Center BYOVA

1. Register a BYOVA data source pointing at your gateway gRPC endpoint.
2. Use schema `5397013b-7920-4ffc-807c-e8a3e0a18f43`.
3. In your WxCC flow, add the Virtual Agent / BYOVA element.
4. Select agent name **My GECX Agent** (must match `agents` in config).

## Deploying to Google Cloud Run

The repo includes a `Dockerfile`, `.dockerignore`, and a Cloud Run config
([`config/config.cloudrun.yaml`](../../config/config.cloudrun.yaml)) selected at
runtime via the `GATEWAY_CONFIG` env var. `main.py` binds the gRPC server to the
`$PORT` Cloud Run injects.

```bash
# 1. Enable APIs
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com --project YOUR_PROJECT_ID

# 2. Grant the Cloud Run runtime service account access to run CES sessions
#    (default compute SA unless you set --service-account on deploy)
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/ces.client"

# 3. Deploy from source (HTTP/2 is required for gRPC)
gcloud run deploy byova-gateway --source . --region us-central1 \
  --allow-unauthenticated --use-http2 --port 8080 --timeout 3600 \
  --project YOUR_PROJECT_ID
```

Notes:

- On Cloud Run no key file is needed; the connector uses the runtime service
  account via Application Default Credentials. That SA needs `roles/ces.client`.
- If Cloud Build fails with a permission error reading the source bucket, grant
  the build service account `roles/cloudbuild.builds.builder`,
  `roles/storage.objectViewer`, `roles/artifactregistry.writer`, and
  `roles/logging.logWriter`.
- Cloud Run exposes a single port (used for the gRPC endpoint), so the web
  monitoring UI is disabled in the Cloud Run config.
- WxCC connects to `SERVICE_URL_HOST:443` over TLS. Configure the gateway's
  JWT validation for the registered BYOVA datasource before production use.
- Verify with `grpcurl` (no reflection, so pass the protos):

```bash
echo '{"customer_org_id":"test"}' | grpcurl -import-path ./proto \
  -proto voicevirtualagent.proto -d @ SERVICE_HOST:443 \
  com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent/ListVirtualAgents
```

## How it works (implementation notes)

These are the non-obvious details that make WxCC <-> CES streaming work. They
are worth understanding if you fork this connector.

### Real-time streaming bridge

`GECXStreamingSession` runs a background thread per conversation that holds one
CES `BidiRunSession` open. WxCC caller audio is pushed onto an inbound queue and
forwarded to CES; CES server messages (STT, agent text, TTS audio, barge-in,
end-of-session) are mapped to BYOVA responses on an outbound queue. The gateway
drains responses while caller audio is flowing and, after gateway speech-end
detection, waits for CES `turn_completed` before returning the final turn to
WxCC. This prevents a response that arrives after `END_OF_INPUT` from remaining
queued when WxCC stops sending caller audio.

All terminal causes pass through one session-scoped decision guard. The first
decision rejects later caller input, finalizes agent audio received before the
decision, half-closes the CES request stream once, and emits at most one
terminal response. Duplicate `EndSession` messages and late CES output are
ignored.

| Terminal cause | WxCC outcome |
|----------------|--------------|
| CES `EndSession` with `session_escalated=true` (or a configured compatibility alias) | `TRANSFER_TO_AGENT` |
| Normal CES `EndSession` | `SESSION_END` |
| Turn-response timeout | `SESSION_END` |
| CES `GoAway` | `SESSION_END` |
| Unexpected CES stream failure/closure | `SESSION_END` |
| WxCC cancellation or request-stream failure | Silent CES cleanup; no continuation is expected |
| Normal WxCC request-stream half-close | Preserve the CES session for the next RPC carrying the same conversation ID |
| Explicit gateway shutdown | Silent CES cleanup |

CES documents [`EndSession`](https://docs.cloud.google.com/python/docs/reference/google-cloud-ces/latest/google.cloud.ces_v1.types.EndSession)
as ending the session and prohibiting further input. CES documents
[`GoAway`](https://docs.cloud.google.com/python/docs/reference/google-cloud-ces/latest/google.cloud.ces_v1.types.GoAway)
as requiring half-close and reconnection. This connector deliberately ends the
WxCC virtual-agent session on `GoAway`; reconnection, retry, and backoff are not
implemented here.

### Speech boundaries

The gateway's central Silero observer owns Webex `START_OF_INPUT` and
`END_OF_INPUT` events. GECX does not run a second local speech detector: every
caller-audio frame is forwarded to CES immediately, and speech-boundary
notifications are used only to coordinate turn completion and response
delivery. Configure the observer under the top-level
`voice_activity_detection` block in `config/config.yaml`.

### Audio format: WxCC expects a self-describing WAV clip

This is the single most important detail. WxCC's `Prompt.audio_content` field
carries **no encoding metadata**, so the bytes must be a **self-describing WAV
file**. Telephony uses **8 kHz, 8-bit, mono mu-law** (`WAVE_FORMAT_MULAW`).

CES streams TTS output as many small raw frames per agent turn. If you forward
those raw frames straight to WxCC, the caller **hears nothing** (WxCC can't tell
what format the bytes are). The connector therefore:

1. **Buffers** all raw CES audio frames for an agent turn.
2. On turn completion (`turn_completed` / `end_session`), **wraps** the whole
   buffer in a WAV header (via `wrap_output_audio` / `_build_wxcc_wav`).
3. Emits **one** complete WAV clip per turn as a single WxCC prompt — the same
   shape the `local_audio_connector` produces.

Barge-in (`interruption_signal`) clears the buffer and any queued audio so the
agent stops talking when the caller interrupts.

> If you change `output_audio_encoding`/`output_sample_rate_hertz`, keep them
> consistent with the WAV header the connector writes. For WxCC telephony, leave
> them at `MULAW` / `8000`.

### Input audio

WxCC sends 8 kHz mu-law. The gateway forwards WxCC's declared encoding and
sample rate in `audio_metadata`; the connector normalizes/converts to the CES
`InputAudioConfig` format. `force_input_format: "wxcc"` remains a compatibility
fallback for clients that omit that metadata.

## Escalation to a human agent

There is **no separate "transfer to live agent" streaming message** in the CES
API. When a CX Agent Studio agent escalates, CES sends an **`EndSession`**
message — the same signal used for a normal "goodbye" — carrying a `metadata`
Struct. The metadata is the only thing that distinguishes an escalation from a
normal end.

Flow:

```
Agent escalates ─► CES EndSession { metadata: {...} }
                 ─► GECXConnector inspects metadata
                     ├─ looks like a transfer ─► TRANSFER_TO_AGENT ─► WxCC routes to a human queue
                     └─ otherwise             ─► SESSION_END (call ends)
```

### 1. Configure the agent to escalate (GECX side)

1. In your agent's instructions/playbook, define **when** to hand off (e.g.
   "if the caller asks for a human, or after two failed attempts, escalate").
2. Make that escalation **end the session and attach
   `session_escalated=true` metadata**. This is the canonical CES escalation
   signal and is checked first. For compatibility, the connector also recognizes
   any of these truthy metadata keys: `transfer`, `transfer_to_agent`,
   `transfer_to_human`, `escalate`,
   `escalation`, `escalated`, `session_escalated`, `handoff`, `human_handoff`,
   `live_agent_handoff` — and also a
   `reason`/`type`/`status`/`intent`/`action` value containing `transfer`,
   `escalat`, `human`, `live agent`, or `handoff`. Optionally include a
   `reason` string.

### 2. Discover exactly what your agent sends

The connector logs the raw metadata on every session end:

```
[<conv>] [GECX] EndSession metadata: {'reason': 'agent_requested_handoff', ...}
```

Trigger one escalation, read that log line, and confirm your keys match. If they
differ, either adjust the agent or override the detection in config (below) —
no code change needed:

```yaml
    # Match whatever your agent actually emits
    transfer_metadata_keys: ["handoff", "route_to_agent"]
    transfer_reason_keywords: ["transfer", "escalat", "human", "handoff"]
    transfer_reason_metadata_keys: ["reason", "type", "action"]
```

When detected, you'll see:

```
gecx_terminal_decision conversation_id=<conv> session=<session> reason=escalation outcome=transfer source=ces_end_session ...
```

### 3. Handle it in the WxCC flow

The Virtual Agent element emits a **Transfer** branch on `TRANSFER_TO_AGENT`.
Wire that branch to a queue that routes to human agents. (A normal
`SESSION_END` ends the virtual-agent interaction without a transfer.)

When CES includes its final spoken announcement with `EndSession`, the GECX
connector sends the CES announcement first and follows it with a prompt-free
terminal response. WxCC skips prompt audio when `TRANSFER_TO_AGENT` shares the
same response, so this ordering lets the full CES announcement play and then
transfers as soon as playback completes. The gateway calculates that gate from
the CES WAV byte rate and data length rather than applying a fixed termination
delay.

The connector also keeps CES text with its matching CES audio until the turn is
complete. This prevents WxCC from synthesizing a separate text-only prompt ahead
of the provider audio, which would duplicate speech and delay later responses.
For GECX, the gateway also places `END_OF_INPUT` on that completed response
instead of sending it as a preceding standalone response; `START_OF_INPUT`
remains immediate.

## Configuration reference

| Key | Required | Description |
|-----|----------|-------------|
| `project_id` | Yes | GCP project ID |
| `location` | Yes | Region (e.g. `us`) |
| `application_id` | Yes | CX app ID |
| `deployment_id` | No | Published deployment ID; omit to use the app root/draft agent |
| `deployment` | No | Full deployment resource path (alternative to `deployment_id`) |
| `entry_agent` | No | Full agent resource path to run a specific sub-agent |
| `api_endpoint` | No | CES endpoint; defaults to `ces.<location>.rep.googleapis.com` |
| `service_account_key` | No | Path to SA JSON; omit to use ADC |
| `initial_message` | No | Text sent when the CES stream opens (default: `Hello`) |
| `enable_partial_responses` | No | Map CES partial outputs to WxCC `PARTIAL` responses |
| `force_input_format` | No | `wxcc` forces 8 kHz MULAW when input metadata is unavailable |
| `turn_response_timeout_seconds` | No | Maximum wait after gateway speech end for CES to complete the agent turn (default: `30`) |
| `transfer_metadata_keys` | No | EndSession metadata keys that, when truthy, trigger a human transfer (see [Escalation](#escalation-to-a-human-agent)) |
| `transfer_reason_keywords` | No | Substrings that, if found in a reason/type metadata value, trigger a transfer |
| `transfer_reason_metadata_keys` | No | Which metadata keys are scanned for `transfer_reason_keywords` |

## Authentication options

| Method | Config keys | Notes |
|--------|-------------|-------|
| Service account | `service_account_key` | Recommended for production |
| ADC | (none) | `gcloud auth application-default login` for dev |
| OAuth | `oauth_client_id`, `oauth_client_secret` | Interactive browser flow |
| Access token | `access_token` | Short-lived (~1 hour), not for production |

Outside Google Cloud, ADC can also use a credential configuration referenced by
`GOOGLE_APPLICATION_CREDENTIALS`. Keep credential files outside the repository
and grant the represented identity `roles/ces.client`.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Agent not listed in WxCC | `agents` name in config matches flow selection |
| Stream fails on start | `roles/ces.client`, API enabled, correct `location` |
| `404` / `UNIMPLEMENTED` on BidiRunSession | Wrong endpoint — must be regional `ces.<location>.rep.googleapis.com` (auto-derived from `location`) |
| `429 Resource exhausted` | CES per-app session quota; retry/backoff or request more quota |
| No audio to caller (silence) | WxCC needs a WAV-wrapped clip, not raw audio. Confirm `Audio out: NNNN bytes WAV` in logs and `output_audio_encoding: MULAW` / `output_sample_rate_hertz: 8000`. See [How it works](#audio-format-wxcc-expects-a-self-describing-wav-clip). |
| Garbled speech | Confirm the gateway logs the declared WxCC encoding/sample rate; use `force_input_format: "wxcc"` only when the client omits metadata |
| No response after `END_OF_INPUT` | Check for `turn_completed` or a turn-completion timeout in `[GECX]` logs; increase `turn_response_timeout_seconds` if the agent regularly needs more than 30 seconds |
| `GoAway` from CES | The connector intentionally emits one `SESSION_END` and half-closes CES; it does not reconnect in the current implementation |
| Import error | `pip install google-cloud-ces` |

## Logs

Search gateway logs for `[GECX]`:

- `Starting conversation` — session created
- `STT` — recognition results from CES
- `Agent` — text responses
- `Audio out: NNNN bytes WAV (MMMM raw)` — one WAV clip emitted per agent turn
  (`NNNN` includes the WAV header; `MMMM` is the raw CES bytes buffered)
- `Barge-in` — interruption signal from CES
- `gecx_terminal_decision` — the winning lifecycle decision, with
  `conversation_id`, CES `session`, `reason`, `outcome`, `source`,
  `elapsed_seconds`, and terminal metadata
- `gecx_duplicate_terminal_suppressed` — a later terminal signal was ignored
- `gecx_late_input_suppressed` / `gecx_late_server_message_suppressed` — caller
  or CES data arrived after the terminal decision
- `gecx_session_join_timeout` — the CES stream thread did not stop within the
  cleanup join window

## Related documentation

- [Google CES Genesys adapter](https://github.com/GoogleCloudPlatform/ces-genesys-adapter) — reference BidiRunSession telephony bridge
- [CX Agent Studio API access](https://docs.cloud.google.com/customer-engagement-ai/conversational-agents/ps/deploy/api-access)
