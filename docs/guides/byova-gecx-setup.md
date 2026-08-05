# BYOVA + Google CX Agent Studio (GECX) Setup Guide

This guide explains how to connect Webex Contact Center (WxCC) BYOVA to an agent built in **CX Agent Studio** (Gemini Enterprise for Customer Experience) using the `GECXConnector` and the CES **BidiRunSession** API.

## Architecture

```
Caller -> WxCC -> BYOVA Gateway (gRPC) -> GECXConnector -> CES BidiRunSession -> CX Agent Studio
```

The connector sends WxCC caller audio to Google as it arrives and forwards CES
8 kHz mu-law output as BYOVA `CHUNK` responses. Normal short CES frames stream
immediately. A guarded speech gate suppresses only an anomalously long,
low-energy prefix and retains bounded pre-roll before prompt speech. Each agent
turn ends with exactly one `FINAL` when CES marks it complete; terminal turns
place `TRANSFER_TO_AGENT` or `SESSION_END` on that final response. Autonomous
CES no-input prompts are pushed directly to the active WxCC stream. Barge-in
is disabled by default and can be enabled only for those prompts after the
interruption path is validated end to end.

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
    suppress_long_leading_audio: true
    output_leading_audio_min_ms: 5000
    output_speech_rms_threshold: 200
    output_speech_start_frames: 2
    output_speech_preroll_ms: 100
    initial_message: "Hello"
    enable_partial_responses: true
    # Keep prompt interruption disabled until the barge-in path is validated.
    barge_in_enabled: false
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
forwarded to CES; CES server messages (STT, agent text, TTS audio,
interruption, and end-of-session) are mapped to BYOVA responses on an outbound
queue. After the gateway emits `END_OF_INPUT`, it consumes that queue
incrementally instead of materializing the complete turn. The first CES audio
frame can therefore reach WxCC before CES emits `turn_completed`.

CES can also produce an autonomous no-input prompt after the preceding
caller-owned response has already reached `FINAL`. The connector publishes
those chunks through the active gateway response sink immediately; it does not
wait for a later caller frame to drain the connector queue. Autonomous chunks
set `is_barge_in_enabled` from the connector's `barge_in_enabled` setting. It
defaults to `false`; set it to `true` only after the interruption path is
validated end to end. When enabled, WxCC continues forwarding caller audio
while CES waits for an interruption or a reply.

When gateway VAD emits `START_OF_INPUT`, the connector opens an isolated caller
turn and waits for CES to acknowledge the committed audio with a recognition
result. An interruption signal does not open the gate because CES can complete
the interrupted no-input turn immediately afterward. CES output produced before
recognition belongs to that overlapping autonomous turn and is suppressed. The
recognized post-input answer then uses the still-active WxCC response stream.

All terminal causes pass through one session-scoped decision guard. The first
decision rejects later caller input, preserves already-queued audio chunks,
half-closes the CES request stream once, and emits at most one terminal
`FINAL`. Duplicate `EndSession` messages and late CES output are ignored.

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
caller-audio frame is ingested while CES responses are being produced.
At an apparent speech end, the gateway holds `END_OF_INPUT` for
`speech_end_grace_ms` (default: `1000`, maximum: `2000`). With the default
`end_silence_ms` value, this creates a bounded two-second natural-pause window.
If speech resumes in that window, GECX removes the endpoint-triggering pause,
merges up to `input_pause_preroll_ms` of the resumed onset, and keeps one CES
input turn. Otherwise it commits the boundary normally. Configure the observer
under the top-level `voice_activity_detection` block in `config/config.yaml`.

### Output audio: raw 8 kHz mu-law BYOVA chunks

CES normally streams TTS output as small frames. The connector places normal
frames directly in `Prompt.audio_content` with `response_type=CHUNK`.
Greeting and caller-triggered reply chunks keep `is_barge_in_enabled=false`.
Autonomous no-input chunks use the `barge_in_enabled` connector setting, which
defaults to `false`; when enabled, it prevents an open CES no-input prompt from
blocking caller interruption. If the first CES frame is both longer than
`output_leading_audio_min_ms` and contains no sustained speech, the connector
drops low-energy frames until speech is detected and keeps
`output_speech_preroll_ms` before that boundary. It does not accumulate a full
turn and does not add a WAV header.

The normal response sequence is:

```text
START_OF_INPUT (standalone FINAL event)
END_OF_INPUT   (CHUNK)
audio          (CHUNK)
audio          (CHUNK)
...
turn complete  (FINAL)
```

A terminal turn uses the same audio chunks, followed by one `FINAL` carrying
`TRANSFER_TO_AGENT` or `SESSION_END`. The initial greeting uses the same
`CHUNK`/`FINAL` pipeline.

The current CHUNK path intentionally supports only 8 kHz mu-law output.
`output_audio_encoding` must remain `MULAW` and
`output_sample_rate_hertz` must remain `8000`; unsupported combinations fail
configuration early. Broader output-format support requires explicit
conversion and validation.

Gateway `START_OF_INPUT` discards already-buffered autonomous prompt output and
isolates CES output until CES recognizes the caller audio. This prevents the
interrupted no-input prompt from finalizing the response stream needed for the
caller's answer. Barge-in is limited to autonomous output; ordered greeting and
caller-response chunks do not advertise interruption.

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

The connector logs metadata key names on every session end without logging
their values:

```
[<conv>] [GECX] EndSession metadata keys: ['reason', 'session_escalated']
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

For short-lived debugging only, `log_raw_terminal_metadata_debug: true` exposes
the full metadata at DEBUG level. Leave it disabled when metadata may contain
customer data or sensitive identifiers.

When detected, you'll see:

```
gecx_terminal_decision conversation_id=<conv> session=<session> reason=escalation outcome=transfer source=ces_end_session ...
```

### 3. Handle it in the WxCC flow

The Virtual Agent element emits a **Transfer** branch on `TRANSFER_TO_AGENT`.
Wire that branch to a queue that routes to human agents. (A normal
`SESSION_END` ends the virtual-agent interaction without a transfer.)

When CES includes its final spoken announcement with `EndSession`, the GECX
connector streams the announcement as ordered `CHUNK` responses and follows it
with one prompt-free terminal `FINAL`. The GECX path no longer calculates a WAV
playback delay; the response stream itself carries the required order.

The connector retains CES text as transcript/fallback state but leaves it off
audio chunks. This prevents WxCC from synthesizing a duplicate text prompt.
For GECX, `START_OF_INPUT` remains an immediate standalone `FINAL` event so
WxCC continues forwarding caller audio through a bounded natural pause.
`END_OF_INPUT` begins the output stream as a `CHUNK` event; audio chunks follow
it, and the output turn closes with one `FINAL`.

Caller audio is buffered from a bounded pre-roll through the gateway's Silero
speech-end boundary, then sent to CES as one contiguous turn. This prevents a
natural pause inside an utterance from becoming an unintended CES barge-in.
After a terminal-sounding response, the connector also allows a short grace
window for an `EndSession` that follows the final TTS frames.

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
| `oauth_client_id` | No | Client ID for the interactive installed-app OAuth flow |
| `oauth_client_secret` | No | Client secret for the interactive installed-app OAuth flow |
| `oauth_token_file` | No | Authorized-user JSON cache (default: `gecx_oauth_token.json`) |
| `initial_message` | No | Text sent when the CES stream opens (default: `Hello`) |
| `enable_partial_responses` | No | Request CES text streaming for logs, terminal-cue detection, and text-only fallback |
| `barge_in_enabled` | No | Allow interruption of autonomous/no-input prompt playback (default: `false`; greeting and caller-triggered replies always remain non-bargeable) |
| `output_sample_rate_hertz` | No | Must be `8000` for the current raw CHUNK path |
| `output_audio_encoding` | No | Must be `MULAW` for the current raw CHUNK path |
| `suppress_long_leading_audio` | No | Guard anomalously long low-energy CES output before prompt speech (default: `true`) |
| `output_leading_audio_min_ms` | No | Minimum first-frame duration that can activate the guard (default: `5000`) |
| `output_speech_rms_threshold` | No | 16-bit linear RMS threshold used to identify speech in decoded mu-law frames (default: `200`) |
| `output_speech_start_frames` | No | Consecutive 20ms frames required to open the output gate (default: `2`) |
| `output_speech_preroll_ms` | No | Audio retained immediately before detected speech (default: `100`) |
| `force_input_format` | No | `wxcc` forces 8 kHz MULAW when input metadata is unavailable |
| `turn_response_timeout_seconds` | No | Maximum wait after gateway speech end for CES to complete the agent turn (default: `30`) |
| `endpointing_silence_ms` | No | Codec-correct silence appended to each buffered caller turn for CES endpoint detection (default: `2000`; one second may leave a turn open until more audio arrives) |
| `input_preroll_ms` | No | Bounded caller audio retained before gateway speech start to avoid clipping (default: `500`) |
| `input_pause_preroll_ms` | No | Maximum onset audio retained while a possible speech end is held, then merged if the caller resumes (default: `250`) |
| `terminal_response_grace_seconds` | No | Wait for delayed `EndSession` after a terminal-sounding TTS turn (default: `3`) |
| `transfer_metadata_keys` | No | EndSession metadata keys that, when truthy, trigger a human transfer (see [Escalation](#escalation-to-a-human-agent)) |
| `transfer_reason_keywords` | No | Substrings that, if found in a reason/type metadata value, trigger a transfer |
| `transfer_reason_metadata_keys` | No | Which metadata keys are scanned for `transfer_reason_keywords` |
| `log_raw_terminal_metadata_debug` | No | Log raw EndSession metadata at DEBUG level; defaults to `false` because values may be sensitive |

## Authentication options

| Method | Config keys | Notes |
|--------|-------------|-------|
| Service account | `service_account_key` | Recommended for production |
| ADC | (none) | `gcloud auth application-default login` for dev |
| OAuth | `oauth_client_id`, `oauth_client_secret`, optional `oauth_token_file` | Interactive browser flow; token JSON is saved atomically with owner-only permissions |
| Access token | `access_token` | Short-lived (~1 hour), not for production |

Outside Google Cloud, ADC can also use a credential configuration referenced by
`GOOGLE_APPLICATION_CREDENTIALS`. Keep credential files outside the repository
and grant the represented identity `roles/ces.client`.
The connector does not deserialize pickle credentials. If an older checkout
created `gecx_oauth_token.pickle`, remove it and complete the OAuth flow once to
create the JSON cache.

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Agent not listed in WxCC | `agents` name in config matches flow selection |
| Stream fails on start | `roles/ces.client`, API enabled, correct `location` |
| `404` / `UNIMPLEMENTED` on BidiRunSession | Wrong endpoint — must be regional `ces.<location>.rep.googleapis.com` (auto-derived from `location`) |
| `429 Resource exhausted` | CES per-app session quota; retry/backoff or request more quota |
| No audio to caller (silence) | Confirm `gecx_first_audio_chunk` appears, the next response is a BYOVA `CHUNK`, and output remains `MULAW` / `8000`. See [Output audio](#output-audio-raw-8-khz-mu-law-byova-chunks). |
| Long static/noise before a prompt | Look for `gecx_long_leading_audio_detected` followed by `gecx_leading_audio_suppressed`; tune the guarded output settings only with captured CES evidence. |
| Garbled speech | Confirm the gateway logs the declared WxCC encoding/sample rate; use `force_input_format: "wxcc"` only when the client omits metadata |
| Agent recognizes the caller but its reply is not audible | Confirm `gecx_pre_input_output_suppressed` is followed by `gecx_caller_input_acknowledged`, `gecx_first_audio_chunk`, and `gecx_streamed_turn_complete` for the same conversation. |
| CES logs a no-input prompt but the caller does not hear it | Confirm `gecx_first_audio_chunk` reports `delivery_mode=async`; its `barge_in_enabled` value should match connector configuration. Verify the active WxCC stream did not cancel before that timestamp. |
| No response after `END_OF_INPUT` | Check for `turn_completed` or a turn-completion timeout in `[GECX]` logs; increase `turn_response_timeout_seconds` if the agent regularly needs more than 30 seconds |
| `GoAway` from CES | The connector intentionally emits one `SESSION_END` and half-closes CES; it does not reconnect in the current implementation |
| Import error | `pip install google-cloud-ces` |

## Logs

Search gateway logs for `[GECX]`:

- `Starting conversation` — session created
- `STT` — recognition results from CES
- `Agent` — text responses
- `gecx_first_audio_chunk` — first raw CES frame published for WxCC, including
  first-frame latency, `async`/`turn` delivery mode, and barge-in state
- `gecx_long_leading_audio_detected` — an anomalously long low-energy CES
  prefix activated the guarded speech gate
- `gecx_leading_audio_suppressed` — the gate opened on sustained speech and
  reports the dropped duration
- `gecx_output_discarded_on_caller_start` — buffered or queued output from the
  prior turn was discarded when gateway VAD detected caller speech
- `gecx_pre_input_output_suppressed` — CES completed an autonomous output turn
  before acknowledging the caller's committed audio
- `gecx_caller_input_acknowledged` — CES recognition opened the response stream
  for post-input CES output
- `gecx_streamed_turn_complete` — one normal `FINAL` emitted after the logged
  chunk and byte totals
- `gecx_terminal_decision` — one terminal `FINAL`, with chunk and byte totals
  but without sensitive metadata values
- `Barge-in` — interruption signal from CES
- `gecx_terminal_decision` — the winning lifecycle decision, with
  `conversation_id`, CES `session`, `reason`, `outcome`, `source`,
  `elapsed_seconds`, and terminal metadata key names
- `gecx_duplicate_terminal_suppressed` — a later terminal signal was ignored
- `gecx_late_input_suppressed` / `gecx_late_server_message_suppressed` — caller
  or CES data arrived after the terminal decision
- `gecx_session_join_timeout` — the CES stream thread did not stop within the
  cleanup join window

## Related documentation

- [Google CES Genesys adapter](https://github.com/GoogleCloudPlatform/ces-genesys-adapter) — reference BidiRunSession telephony bridge
- [CX Agent Studio API access](https://docs.cloud.google.com/customer-engagement-ai/conversational-agents/ps/deploy/api-access)
