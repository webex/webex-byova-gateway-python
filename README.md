# Webex Contact Center BYOVA Gateway

[![License: Cisco Sample Code](https://img.shields.io/badge/License-Cisco%20Sample%20Code-blue.svg)](LICENSE)

A Python gateway that connects Webex Contact Center (WxCC) to external voice virtual-agent
providers through the BYOVA gRPC interface.

This repository is functional sample code for customers and partners building or evaluating
a BYOVA integration. It is not a managed connector or a production-ready deployment. The
customer or implementation partner owns the gateway adaptation, hosting, security, capacity,
observability, and production operations.

If you are deciding whether BYOVA fits an existing voice agent, start with
[Evaluating BYOVA](docs/CUSTOMER_EVALUATION.md). If you have completed a proof of concept,
continue with [Production Readiness](docs/PRODUCTION_READINESS.md).

If you want to validate the Webex-facing path before choosing a voice-agent provider, use
the [Local Audio Connector Configuration](docs/LOCAL_AUDIO_CONFIGURATION.md) guide.
For Google CX Agent Studio, use the
[GECX Setup Guide](docs/guides/byova-gecx-setup.md).

## What the Gateway Does

At runtime, WxCC opens a bidirectional gRPC stream to the registered gateway endpoint. The
gateway validates the signed Webex token, routes the conversation to the configured
connector, and translates audio and events between WxCC and the voice-agent provider.
Caller ingestion, ordered connector processing, and response delivery use independent
workers with bounded per-stream queues, so WxCC can continue sending caller frames while a
connector is still producing output.

The sample includes:

- A BYOVA gRPC server with `ListVirtualAgents` and `ProcessCallerInput`
- JWT validation for the WxCC data plane
- Optional BYODS datasource registration and pre-expiry JWS renewal
- A configuration-driven connector router
- Local audio, AWS Lex, and Google CX Agent Studio connectors
- Immediate 8 kHz mu-law BYOVA `CHUNK` output for Google CX Agent Studio,
  with guarded suppression of anomalously long low-energy pre-roll and one
  ordered `FINAL` per normal or terminal turn
- gRPC and HTTP health checks
- A development monitoring dashboard
- Unit tests and local gRPC smoke-test utilities

## Quick Start

> **Recommended for first-time setup:** Follow the complete
> [BYOVA with AWS Lex guide](https://developer.webex.com/webex-contact-center/docs/byova-and-aws-lex).
> It covers Webex organization enablement, the voice agent, public hosting, Service App
> authorization, data-source registration, gateway configuration, and the Contact Center
> call flow. If you have not selected a provider, use the
> [Local Audio Connector Configuration](docs/LOCAL_AUDIO_CONFIGURATION.md) guide for a
> vendor-neutral end-to-end validation. For Google CX Agent Studio, use the
> [GECX Setup Guide](docs/guides/byova-gecx-setup.md). The abbreviated steps below only
> install and run the gateway code.

### Webex Prerequisites for End-to-End Testing

Before WxCC can connect to this gateway, you need:

- A Webex Contact Center sandbox or nonproduction organization with BYOVA enabled
- A Service App configured with the BYODS scopes, Voice Virtual Agent schema, and the data
  exchange domain for your gateway
- Authorization of that Service App by an administrator in the target organization
- A publicly reachable TLS-enabled gRPC server URL on the authorized domain
- An `ACTIVE` BYOVA data-source registration whose URL exactly matches the public server URL;
  the gateway can create and renew this registration when datasource management is enabled
- A Contact Center AI virtual-agent configuration and a test flow that uses the Virtual
  Agent V2 activity
- A configured gateway connector: use the local audio connector for a vendor-neutral
  validation, or configure an external voice agent and its compatible connector

If any of these items are missing, stop here and use the
[full setup guide](https://developer.webex.com/webex-contact-center/docs/byova-and-aws-lex)
or the [local audio guide](docs/LOCAL_AUDIO_CONFIGURATION.md), depending on the connector you
are evaluating, before attempting an end-to-end call. The registered data-source URL must
also exactly match `jwt_validation.datasource_url` in `config/config.yaml`.

### Local Software Prerequisites

- Python 3.8 or later
- macOS, Linux, or Windows

### Install

```bash
git clone https://github.com/webex/webex-byova-gateway-python.git
cd webex-byova-gateway-python
python -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python -m grpc_tools.protoc \
  -I./proto \
  --python_out=src/generated \
  --grpc_python_out=src/generated \
  proto/*.proto
```

On Windows, activate the virtual environment with `venv\Scripts\activate`.

### Configure a Local-Only Run

The checked-in configuration enables gRPC JWT validation without committing a datasource
URL, so a fresh checkout intentionally refuses to start until it is configured.

For a local-only test that is not connected to Webex, set the following in
`config/config.yaml`:

```yaml
authentication:
  enabled: false

jwt_validation:
  enabled: false
```

Never use disabled authentication for a Webex-connected or production endpoint. For an
end-to-end test, configure the exact registered datasource URL and keep JWT enforcement
enabled.

### Configure Automatic Datasource Management

The optional datasource lifecycle uses
[`webex-byods-sdk`](https://github.com/WebexCommunity/webex-python-byods-sdk) to discover or
register this gateway before gRPC starts accepting traffic and to renew its JWS before
expiry. Configure `jwt_validation.datasource_url`, then enable:

```yaml
data_source:
  enabled: true
  auth:
    type: "oauth_refresh"
    client_id_env: "WEBEX_BYODS_CLIENT_ID"
    client_secret_env: "WEBEX_BYODS_CLIENT_SECRET"
    refresh_token_env: "WEBEX_BYODS_REFRESH_TOKEN"
```

Set the named environment variables from an authorized Service App with
`spark-admin:datasource_read` and `spark-admin:datasource_write`. The gateway discovers an
exact URL/schema/audience/subject match when no datasource ID is configured, reconciles
configuration drift, and renews the token 60 minutes before expiry by default. See the
[Configuration Reference](config/README.md#byods-datasource-lifecycle) for all settings and
the static-token development option.

### Run

```bash
python main.py
```

Then check:

```bash
curl http://localhost:8080/api/status
python test_health.py
```

The gRPC server listens on `localhost:50051`, and the development monitoring interface
listens on `http://localhost:8080`. Press `Ctrl+C` to stop the gateway gracefully.

See [Local Development](docs/LOCAL_DEVELOPMENT.md) for dashboard authentication, public
endpoint testing, logs, and troubleshooting.

## Documentation

| Audience or task | Guide |
| --- | --- |
| Complete a first end-to-end AWS Lex setup (recommended) | [BYOVA with AWS Lex](https://developer.webex.com/webex-contact-center/docs/byova-and-aws-lex) |
| Evaluate BYOVA for an existing voice agent | [Customer Evaluation](docs/CUSTOMER_EVALUATION.md) |
| Validate BYOVA before choosing a voice-agent provider | [Local Audio Connector Configuration](docs/LOCAL_AUDIO_CONFIGURATION.md) |
| Install and run the sample locally | [Local Development](docs/LOCAL_DEVELOPMENT.md) |
| Configure the gateway and connectors | [Configuration Reference](config/README.md) |
| Configure runtime JWT validation | [gRPC JWT Authentication](docs/JWT_AUTHENTICATION.md) |
| Run automated and service tests | [Testing Guide](docs/TESTING.md) |
| Configure the monitoring dashboard | [Monitoring Interface](src/monitoring/README.md) |
| Add or configure connectors | [Connector Guide](src/connectors/README.md) |
| Configure AWS Lex | [AWS Lex Configuration](docs/AWS_LEX_CONFIGURATION.md) |
| Configure Google CX Agent Studio | [GECX Setup Guide](docs/guides/byova-gecx-setup.md) |
| Configure TLS and network security | [Security Configuration](docs/Security-Configuration.md) |
| Prepare a derivative for production | [Production Readiness](docs/PRODUCTION_READINESS.md) |

The [documentation index](docs/README.md) provides additional component references.

## Interfaces

### gRPC

- `ListVirtualAgents`: Returns the configured virtual agents.
- `ProcessCallerInput`: Handles bidirectional caller audio, DTMF, and conversation events.
- `grpc.health.v1.Health/Check`: Reports service health.

The protocol definitions are in `proto/` and originate from the Webex Voice Virtual Agent
schema.

### HTTP Monitoring

- `GET /`: Development monitoring dashboard
- `GET /api/status`: Gateway and connector status
- `GET /api/connections`: Recent connection information
- `GET /health`: HTTP process health

The monitoring interface is a development and diagnostic tool. Do not expose it in
production without the controls described in the production guide.

## Included Connectors

- **Local Audio**: Uses the included WAV files for local development and vendor-neutral
  end-to-end validation. See [Local Audio Connector Configuration](docs/LOCAL_AUDIO_CONFIGURATION.md).
- **AWS Lex**: Connects to Amazon Lex V2 through the standard AWS SDK credential chain.
- **Google CX Agent Studio**: Streams caller audio to Gemini Enterprise for Customer
  Experience through CES `BidiRunSession`. Caller speech starts an isolated response turn,
  so an overlapping CES no-input prompt cannot consume the caller's post-input reply. See the
  [GECX Setup Guide](docs/guides/byova-gecx-setup.md).

Connectors implement `IVendorConnector` and are loaded from `config/config.yaml`. See the
[Connector Guide](src/connectors/README.md) for the interface contract and extension pattern.

## Project Structure

```text
webex-byova-gateway-python/
├── audio/              # Local connector audio files
├── config/             # Gateway and connector configuration
├── docs/               # Evaluation, security, testing, and operations guides
├── proto/              # BYOVA and health protocol definitions
├── scripts/            # Runtime release tooling
├── src/
│   ├── auth/           # gRPC JWT validation
│   ├── connectors/     # Virtual-agent connectors
│   ├── core/           # Datasource lifecycle, gateway server, routing, and health
│   ├── generated/      # Locally generated gRPC modules
│   ├── monitoring/     # Development monitoring interface
│   └── utils/          # Audio utilities
├── tests/              # Automated test suite
├── tools/              # Local development and end-to-end test tools
├── main.py             # Application entry point
└── requirements.txt    # Python dependencies
```

## Build a Runtime Release Artifact

Build EC2 and server releases with the allowlisted runtime artifact builder:

```bash
scripts/build-runtime-release.sh \
  --ref HEAD \
  --output /tmp/byova-gateway-runtime.tar.gz
```

The archive contains only the Python gateway runtime: `main.py`, Python dependency
metadata, `audio/`, `config/`, `proto/`, and `src/`. It deliberately excludes `tools/`,
`tests/`, `docs/`, JavaScript package manifests and lockfiles, and macOS AppleDouble files.

`tools/byova_e2e/` is a local validation utility. Its browser dependencies must not be copied
to an EC2 gateway or included in an image or release archive. Deploying the whole repository
can cause host scanners to report development-only dependencies as if the gateway loaded
them at runtime.

Before deployment, scan the generated archive and verify its checksum. Keep environment
configuration and secrets outside the artifact and inject them through the deployment
system.

## Development

To add a connector:

1. Create a connector class in `src/connectors/`.
2. Inherit from `IVendorConnector` and implement every required method.
3. Add the connector to `config/config.yaml`.
4. Add unit and integration tests.
5. Validate the full conversation lifecycle, including escalation and cleanup.

If a proto changes, regenerate the local Python modules:

```bash
python -m grpc_tools.protoc \
  -I./proto \
  --python_out=src/generated \
  --grpc_python_out=src/generated \
  proto/*.proto
```

## Support and Contributing

For BYOVA concepts and onboarding, see the official
[BYOVA developer guide](https://developer.webex.com/webex-contact-center/docs/bring-your-own-virtual-agent).
For repository changes, open an issue or pull request with reproduction steps and relevant
logs that do not contain credentials, caller audio, or customer data.

Maintainer: [@adweeks](https://github.com/adweeks)

## License

[Cisco Sample Code License v1.1](LICENSE) © 2018 Cisco and/or its affiliates.

This sample code is not supported by Cisco TAC and is not tested for production quality or
performance. It is provided for example purposes only, “AS IS,” with all faults and without
warranty or support of any kind.
