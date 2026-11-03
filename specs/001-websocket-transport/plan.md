# Implementation Plan: BYOVA WebSocket Transport

## Context

Baseline: WebSocket branch commit `85cd30a`. Python/aiohttp provides the WxCC
listener; Pydantic defines wire models; the existing protobuf-based conversation
engine and connector router remain shared. Native CES WebSocket is a separate
GECX connector subclass. No new dependency is needed for readiness fixes.

The October 18 extension adds a separate Lex WebSocket adapter over the shared
RecognizeUtterance provider. It introduces no new package, updates the AWS SDK
minimum versions to the tested stable set, separates discovery namespaces, and
retains Lex's ten-digit collection policy on WebSocket responses. Tests cover
the shared DTMF symbol conversion, real SDK request models with Stubber, and
socket discovery/voice/DTMF/disconnect using fake AWS responses (FR-003, FR-006,
FR-007). Real WxCC-to-Lex acceptance remains pending.

## Constitution check

The change preserves the reference purpose, explicit transport boundary, existing
auth validation, shared VAD/routing, private infrastructure boundary, and runtime
allowlist. Local validation and live acceptance are tracked separately.

## Changes and requirement mapping

| Work | Files | Requirements |
| --- | --- | --- |
| Keep worker slots until actual completion; suppress cancelled queued work | `src/transports/websocket_server.py` | FR-002, FR-004 |
| Reserve one bounded cleanup worker and defer its shutdown until finalizers finish | same | FR-004 |
| Rebalance short tails and encode audio only at its final wire boundary | `src/transports/websocket_adapter.py` | FR-003, FR-005 |
| Preserve behavior with component/socket regressions and full suite | `tests/test_websocket_*.py` | FR-001 through FR-006 |
| Correct Local Audio framing documentation and prepare live acceptance | `docs/WEBSOCKET_*.md`, this feature directory | SC-001 through SC-004 |

## Validation order

1. Reproduce the three reported defects with focused tests before fixing code.
2. Run WebSocket adapter/socket tests and formatting/lint on changed Python files.
3. Run the full gateway suite and E2E-tooling suite using an activated environment.
4. Exercise real local discovery/session listeners without external services.
5. Self-review cancellation, failure, teardown, media boundaries, and private data.
6. Commit locally and verify the allowlisted runtime archive from the final commit.
7. Leave live matrix rows pending; do not deploy or place calls in this delivery.

## Known limits

Python cannot forcibly stop a running provider thread. Reserved cleanup remains
serialized and shutdown has a finite drain budget. A provider that never returns
requires investigation; do not hide it by releasing worker slots early or running
its cleanup on the event loop.

These artifacts use the Spec Kit constitution/spec/plan/tasks layout. They do
not claim an automated `speckit.analyze` run; consistency is checked against the
requirement/task mapping and repository tests.

## Local validation record — 2026-10-17

- Gateway suite: 625 passed on Python 3.12; the existing `audioop` deprecation
  warning remains. E2E-tooling suite: 106 passed.
- Changed Python files passed Ruff lint and formatting; `git diff --check` passed.
- Both checked-in E2E plans validated without placing calls (2 Local Audio,
  7 GECX scenarios).
- Real local process: WebSocket discovery, complete welcome/DTMF 5 transfer and
  DTMF 6 session-end streams, audio bounds/FINAL termination, gRPC discovery,
  and SIGTERM during an active call all passed; shutdown closed the socket with 1001.
- Independent review reproduced late-start and cancelled-job teardown edges;
  both were fixed and covered by regressions. Final review had no actionable findings.
- The runtime allowlist archive test passed against the committed code. The
  local-ready bundle includes regenerated protobuf modules and excludes tests,
  tools, documentation, and specification scaffolding.
- A single synthetic 4 MiB raw-response comparison produced identical frame
  counts; traced peak allocation fell from 19.3 MiB to 9.9 MiB after removing the
  full-response base64 round trip. This is a local sample, not a load benchmark.
- Live WxCC/CES acceptance remains pending under local-ready delivery.
