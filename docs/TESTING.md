# Testing Guide

This guide covers the automated test suite and local smoke tests for the HTTP monitoring and
gRPC services.

## Prerequisites

Activate the project virtual environment and install dependencies:

```bash
source venv/bin/activate
python -m pip install -r requirements.txt
```

Generate the gRPC stubs before tests or smoke checks that import generated modules:

```bash
python -m grpc_tools.protoc \
  -I./proto \
  --python_out=src/generated \
  --grpc_python_out=src/generated \
  proto/*.proto
```

## Automated Tests

Run the full suite with the repository test runner:

```bash
python run_tests.py
```

Or invoke pytest directly:

```bash
python -m pytest tests/
```

Run a single file or test:

```bash
python run_tests.py tests/test_jwt_validation.py
python run_tests.py tests/test_wxcc_gateway_server.py::TestConversationProcessor
```

List collected tests:

```bash
python run_tests.py --list
```

The default suite uses mocks for external services. Tests marked `integration`, `aws`, or
`slow` may have additional requirements; inspect the selected test before running it against
real services.

## Start a Local Test Server

For local-only smoke tests, disable dashboard authentication and gRPC JWT validation as
described in [Local Development](LOCAL_DEVELOPMENT.md), then run:

```bash
python main.py
```

Do not use disabled authentication for a public or production endpoint.

## HTTP Smoke Tests

With the gateway running:

```bash
curl http://localhost:8080/api/status
curl http://localhost:8080/api/connections
curl http://localhost:8080/health
```

For dashboard behavior and OAuth testing, see the
[Monitoring Interface documentation](../src/monitoring/README.md).

## gRPC Health Checks

Use the included Python client:

```bash
python test_health.py
```

Expected services include:

- Overall gateway health
- `byova.gateway`
- `byova.VoiceVirtualAgentService`

Health status values are `SERVING`, `NOT_SERVING`, or `SERVICE_UNKNOWN`.

## Test With grpcurl

The server does not enable gRPC reflection, so provide the local proto files.

Overall health:

```bash
grpcurl -plaintext \
  -import-path proto \
  -proto health.proto \
  localhost:50051 \
  grpc.health.v1.Health/Check
```

Gateway service health:

```bash
grpcurl -plaintext \
  -import-path proto \
  -proto health.proto \
  -d '{"service":"byova.gateway"}' \
  localhost:50051 \
  grpc.health.v1.Health/Check
```

List the configured virtual agents:

```bash
grpcurl -plaintext \
  -import-path proto \
  -proto voicevirtualagent.proto \
  -d '{"customerOrgId":"local-test"}' \
  localhost:50051 \
  com.cisco.wcc.ccai.media.v1.VoiceVirtualAgent/ListVirtualAgents
```

When JWT validation is enabled, add the valid runtime token as request metadata rather than
disabling enforcement:

```text
-H 'authorization: Bearer <JWT_TOKEN>'
```

## End-to-End Validation

A production-candidate connector needs more than unit and health tests. Validate:

- Agent discovery and conversation start
- Caller audio and response audio in both directions
- DTMF and input events
- Human-agent escalation and transcript behavior
- Normal termination, cancellation, timeout, and reconnect behavior
- Invalid authentication and dependency failure
- Caller-visible latency and audio quality under representative concurrency

Use [Production Readiness](PRODUCTION_READINESS.md) for load, resilience, security, and
operational launch criteria.

## Related Documentation

- [Detailed test-suite notes](../tests/README.md)
- [Local development](LOCAL_DEVELOPMENT.md)
- [JWT authentication](JWT_AUTHENTICATION.md)
- [Return to the project README](../README.md)
