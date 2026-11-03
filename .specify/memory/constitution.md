# BYOVA Gateway Constitution

## I. Reference implementation

Deliver functional, understandable sample code. Do not claim production
readiness or add speculative provider abstractions.

## II. Shared behavior, explicit transports

Use the existing connector contract, router, conversation engine, and gateway
VAD. Model WebSocket JSON explicitly at its boundary; keep WxCC-facing protocol
selection separate from the provider protocol. Preserve existing gRPC behavior.

## III. Trust and resource boundaries

Validate incoming messages and datasource-bound JWTs. Bound media sizes, queues,
and executor work. Blocking provider calls and cleanup must stay off the socket
event loop. Keep credentials and environment-specific infrastructure private.

## IV. Evidence before completion

Add regression tests for meaningful behavior changes and run relevant local
checks. Distinguish local success from live WxCC/provider acceptance; correlate
live evidence by commit and conversation ID. Honor the selected delivery level.

## V. Runtime isolation

Build runtime archives with the repository allowlist and regenerate protobufs.
Keep tests, tools, specifications, documentation, and development dependencies
outside runtime release artifacts.

Version: 1.0.0 | Ratified: 2026-10-17 | Last amended: 2026-10-17
