# Feature Specification: BYOVA WebSocket Transport

Status: implemented and locally validated; live acceptance pending.
Delivery level for this work: local-ready.

## User scenarios and acceptance

### US1: Select a transport without rewriting providers (P1)

Given gRPC, WebSocket, or combined mode, when the gateway starts, only the
selected listeners and independent datasource profiles are initialized.
WebSocket discovery and direct agent selection apply the same eligibility rules.
The existing connector router and conversation engine handle both transports.

### US2: Complete a WebSocket call (P1)

Given an authenticated datasource-bound upgrade, the first call message is
SESSION_START. Voice, DTMF, custom/no-input events, provider output, transfer,
and termination preserve their shared conversation semantics. Ordered audio
CHUNKs contain 100–65,536 bytes and end with the required FINAL terminator.
Invalid messages, lifecycle changes, and sustained queue pressure are rejected.

### US3: Disconnect safely under load (P1)

When a waiting coroutine is cancelled, its running or queued executor job keeps
capacity until the job is consumed/completed. Cancelled queued work produces no
provider side effects. Worker failures and rejected submissions release capacity.
Provider cleanup uses bounded reserved capacity and never runs on the socket
event loop. Shutdown preserves pending cleanup and releases each conversation
lease once provider teardown completes within the configured drain budget.

### US4: Select native CES WebSocket independently (P2)

The native CES connector uses the allow-listed authenticated WebSocket endpoint
and reuses GECX audio/lifecycle behavior. Separate agent identities distinguish
CES gRPC and CES WebSocket when both are configured.

### US5: Select a separate Lex WebSocket adapter (P2)

`AWSLexWebSocketConnector` advertises only the WxCC WebSocket transport and
uses a distinct bot-ID namespace from `AWSLexConnector`. Both share the Lex
RecognizeUtterance provider and retain independent session state. The WebSocket
adapter buffers caller utterances, returns complete WAV FINAL responses, and
converts BYOVA DTMF enums into their actual telephony symbols.

## Functional requirements

- FR-001: Use separate strict WebSocket JSON models and an adapter to the shared engine.
- FR-002: Enforce JWT before upgrade, bounded frames/queues/work, stable session identity,
  increasing sender sequence numbers, and transport-specific discovery filtering.
- FR-003: Preserve voice/DTMF collection metadata, handoff data, and terminal ordering.
- FR-004: Keep worker accounting correct through cancellation and cleanup off the event loop.
- FR-005: Frame audio directly from provider bytes without redundant base64 round trips.
- FR-006: Preserve gRPC behavior and build runtime artifacts only from allowlisted paths.
- FR-007: Keep the Lex adapters independently discoverable and validate their shared
  AWS SDK request contract, audio buffering, DTMF conversion and disconnect cleanup.

## Success criteria

- SC-001: Automated gateway and E2E-tooling suites pass locally.
- SC-002: Regression tests reproduce the reported capacity, saturated-cleanup, and
  short-tail failures before fixes and pass afterward; also cover startup/disconnect,
  queued cleanup, and cancelled-job finalization.
- SC-003: Local discovery/session smoke checks pass against the real listener.
- SC-004: Every applicable row in the [live acceptance matrix](../../docs/WEBSOCKET_LIVE_TESTING.md)
  has correlated evidence from the intended deployed commit before live acceptance.

## Scope boundaries

The original baseline did not opt in additional providers. The October 18 Lex
extension adds a separate, explicitly configured WebSocket adapter and local
validation. It does not deploy the adapter, create a PR, or claim live Lex
acceptance. Earlier GECX live evidence is recorded in the acceptance matrix;
remaining live checks still require correlated evidence.
