# Resume WebSocket live testing

The WebSocket transport and native CES connector are implemented. The October
17, 2026 development rollout runs runtime commit `cda96b7`. A real WxCC call
completed two caller turns over native CES WebSocket, with both turns confirmed
by provider recognition events. A retained gRPC control also completed two
recognized turns. Full live acceptance still requires the remaining matrix
checks below. This gateway remains functional sample code.

The live run exposed a streamed-prompt boundary defect: provider audio CHUNKs
could finish with a prompt-less FINAL, leaving WxCC in playback and dropping
caller input. The sender now terminates that stream with explicit empty audio, including
an abandoned stream before caller speech starts. Its synthetic FINAL preserves
the previous audio frame's input collection settings. Local regression coverage includes normal and terminal responses, including
interleaved input-boundary events. The deployed image passed its registry scan
with no reported findings; gateway tests passed (644 tests), and caller-tool
tests passed (118 tests).

## Observed development results (October 17–18, 2026)

| Check | Observed result |
| --- | --- |
| Native CES WebSocket | Two recognized caller turns, a long recognized request with streamed output, and goodbye with remote disconnect. Normal-response latency was 3.09 seconds against a six-second target. |
| Transfer | Recognized request, `TRANSFER_TO_AGENT`, forwarded summary metadata, and the configured WxCC announcement. This proves gateway escalation, not a staffed-agent handoff. |
| Natural pause | With the optional fast recognition endpoint disabled, a 1.8-second pause stays in one gateway turn and CES updates recognition to the complete utterance. |
| Authentication | Anonymous discovery/upgrade and invalid-token discovery return 401. |
| Retained gRPC control | Two recognized caller turns passed on the independent retained service. |
| Local Audio DTMF | The official Calling sample delivered 5 (transfer) and 6 (session end plus remote disconnect). Three other calls failed despite sender tone events. Delivery remains intermittent; failures correlate with earlier speech END_OF_INPUT. |

The private development profile permits interruption of autonomous CES
reprompts and uses an agent-specific caller prompt gate. Greetings and
caller-triggered replies retain their existing non-interruptible behavior.
The former 200 ms recognition-assisted override cut off the second half of the
pause fixture; the target now uses the reference configuration's normal pause
window. Recheck latency when changing endpointing settings.

Reliable live DTMF delivery remains an acceptance blocker. Failed calls contain
no gateway DTMF input, while successful calls prove the JSON/protobuf conversion
and Local Audio handlers work. Hold digit, media and duration fixed while varying
submission before/after speech endpointing; the observed correlation does not
establish a root cause. Flow Designer's handoff variable value,
active-call shutdown/drain, and load behavior still need their own live checks.
Keep exact call artifacts, configuration fingerprints, and deployment identities
in the private handoff rather than this shared repository.

## Lex WebSocket adapter: local validation only

`AWSLexWebSocketConnector` is a separate WxCC-facing adapter with distinct bot
discovery IDs. It shares the existing utterance-buffered Lex provider and emits
complete WAV `FINAL` responses. Local tests cover discovery and transport
isolation, voice, DTMF mapping, SDK request validation and disconnect cleanup.
The AWS SDK baseline is Boto3/Botocore 1.43.114 and S3Transfer 0.19.2.
This adapter has not been deployed or validated through a real WxCC-to-Lex call.
See [Lex setup](AWS_LEX_CONFIGURATION.md#separate-websocket-adapter).

## 1. Establish the local baseline

From the repository root, activate a virtual environment with
`requirements-dev.txt` installed, then run:

```bash
source venv/bin/activate
python -m grpc_tools.protoc -I./proto \
  --python_out=src/generated --grpc_python_out=src/generated proto/*.proto
python -m pytest tests/
PYTHONPATH=tools/byova_e2e/src python -m pytest tools/byova_e2e/tests/
```

For a local socket smoke check, start the gateway in one terminal:

```bash
GATEWAY_CONFIG=config/websocket_local_example.yaml python main.py
```

In another terminal with the same virtual environment activated:

```bash
python tools/websocket_smoke.py --url ws://127.0.0.1:58765 --mode list
python tools/websocket_smoke.py --url ws://127.0.0.1:58765 --mode session \
  --agent-id 'Local Audio: Local Playback'
```

Discovery must list Local Audio. The session probe now reads through FINAL,
checks conversation/sequence ordering, validates base64 audio and requires the
explicit empty-audio terminator after streamed audio. Early disconnects, error
frames and incomplete streams fail the command. `--timeout` bounds the whole
response, so a trickle of frames cannot keep an incomplete probe alive forever.
Default session output contains only conversation IDs and frame/audio byte
counts; `--include-audio` explicitly prints complete frames with call content.

Use a small concurrent run against the local listener to check that sessions
complete and remain open for five seconds:

```bash
python tools/websocket_smoke.py --url ws://127.0.0.1:58765 --mode session \
  --agent-id 'Local Audio: Local Playback' --sessions 8 --hold-seconds 5
```

For a shutdown check, replace the hold setting with
`--hold-seconds 30 --expect-shutdown`, then stop the local gateway with Control-C
after eight `session_ready` progress events appear on stderr. Every session
must finish its initial response and close with
1001 within the hold window. A normal close, early disconnect or missing
shutdown fails. Check gateway/provider cleanup separately: a 1001 receipt alone
does not prove that their resources were released. `--sessions` is limited to
1–100 and hold time to 0–300 seconds; each concurrent call gets a unique ID.
`BYOVA_WEBSOCKET_TOKEN` supplies the existing authentication header for an
approved authenticated target without placing the token on the command line.

These direct socket checks do not place a phone call or certify WxCC media,
DTMF, provider recognition, Flow variables or production capacity. The local
socket regression tests also check shutdown with eight active conversations,
one provider cleanup per conversation and no remaining registry leases.

## 2. Prepare the live target when returning

- Record the selected source commit and verify the target runs that same commit.
  Build releases only with `scripts/build-runtime-release.sh --ref HEAD --output
  /tmp/byova-gateway-runtime.tar.gz` after committing the intended changes.
- Use the existing private deployment procedure and configuration. Keep hostnames,
  resource IDs, credentials, and routing outside this shared example repository.
- Verify WSS routing for both `/v1/va` and `/v1/listVirtualAgents`. Enable enforced
  JWT validation and the distinct WebSocket datasource/Service App profile; the
  loopback-only unauthenticated example is unsuitable for the live target.
- Select the intended provider hop explicitly. `GECXConnector` uses CES gRPC;
  `GECXWebSocketConnector` uses CES WebSocket. Give them distinct agent IDs and
  transport restrictions when configured together. See the
  [GECX setup guide](guides/byova-gecx-setup.md).
- Use a dedicated test caller and approved WxCC test flow/destination. Configure
  the E2E runner's private gateway-events access as described in its
  [JSON test and gateway-evidence guide](../tools/byova_e2e/README.md#define-tests-in-json).

## 3. Run the acceptance matrix

| Scenario | Pass evidence |
| --- | --- |
| Authenticated discovery | Intended WebSocket agents appear; disabled agents do not. Missing/invalid JWT is rejected before upgrade. |
| Local Audio menu | DTMF 5 plays the transfer prompt and emits TRANSFER_TO_AGENT; DTMF 6 plays goodbye and emits SESSION_END. |
| Native CES voice | Welcome, a normal request, a long response, and a second caller turn are audible in order; each stream completes. |
| Natural pause | The configured pause is handled as one caller turn according to the existing GECX regression plan. |
| Autonomous/no-input output | A provider-initiated prompt reaches the caller without another caller frame. |
| Barge-in | Behavior matches the connector configuration; test enabled and disabled behavior only where supported by the agent/flow. |
| Transfer and metadata | Announcement precedes the terminal event; expected handoff summary reaches the configured Flow Designer variable. |
| Peer disconnect | One provider cleanup, one gateway end event, and no remaining conversation lease/session. |
| Gateway shutdown | Active calls close with 1001, provider cleanup completes within the drain budget, and new upgrades are rejected during shutdown. |
| gRPC regression | Existing gRPC discovery, voice, transfer, and termination still work with their independent datasource. |

The existing E2E plans already cover the Local Audio terminal controls and GECX
voice/terminal scenarios. From `tools/byova_e2e`, using its configured environment:

```bash
byova-e2e validate --config config/local-audio-dtmf.spec.json --list
byova-e2e validate --config config/gecx-regression.spec.json --list
```

Run each Local Audio test against the test destination:

```bash
byova-e2e run --destination "$BYOVA_TEST_DESTINATION" \
  --config config/local-audio-dtmf.spec.json --test dtmf-transfer
byova-e2e run --destination "$BYOVA_TEST_DESTINATION" \
  --config config/local-audio-dtmf.spec.json --test dtmf-session-end
```

Run the applicable listed GECX test IDs with the same `--config`/`--test` pattern,
adding `--gateway-transport websocket --gateway-agent-id "$BYOVA_TEST_AGENT_ID"`
to bind evidence to the selected native CES WebSocket agent. Supply these values
locally; do not commit deployment-specific test plans. Provider prompts and
handoff expectations must match the selected agent's actual behavior.

## 4. Record acceptance

For every run, retain the deployed commit, non-secret configuration fingerprint,
test ID, UTC time window, conversation ID, gateway transport, provider agent ID,
caller result, gateway terminal/cleanup events, and provider session evidence.
Keep recordings, transcripts, raw logs, and private deployment details in the
approved private evidence location.

A caller recording alone does not prove provider cleanup or handoff metadata.
For every speech scenario, confirm the expected number of provider recognition
events as well as caller audio. An autonomous no-input reprompt can satisfy an
audio-only response expectation even when the caller utterance was discarded.
Tune the private profile's remote-silence gate for the selected agent. Short
intervals can inject within a greeting; long intervals can overlap a no-input
reprompt. Record that interval with the configuration fingerprint.
Mark each matrix row pass/fail/pending and link its evidence. A provider cleanup
that exceeds the drain budget is a failed shutdown check; Python cannot forcibly
stop a blocked provider thread. Do not label the feature live-verified until
every applicable row passes on the tested commit.

The feature's Spec Kit-compatible acceptance criteria and task status are under
[`specs/001-websocket-transport`](../specs/001-websocket-transport/spec.md).
