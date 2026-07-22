# Local Development Guide

This guide covers local installation, development-only configuration, running the gateway,
the monitoring interface, public endpoint testing, and common local problems.

## Prerequisites

- Python 3.8 or later
- macOS, Linux, or Windows

Always use a virtual environment for this project.

These local prerequisites are sufficient only for running the code and its local connector.
An end-to-end WxCC test also requires a BYOVA-enabled organization, an authorized Service
App, a public TLS-enabled gateway URL, an `ACTIVE` data-source registration for that exact
URL, a configured gateway connector, and a Contact Center flow using Virtual Agent V2.
Use the [Local Audio Connector Configuration](LOCAL_AUDIO_CONFIGURATION.md) guide for a
vendor-neutral sandbox validation. For a complete AWS Lex integration, follow the
[BYOVA with AWS Lex guide](https://developer.webex.com/webex-contact-center/docs/byova-and-aws-lex)
before attempting an end-to-end call.

## Install

1. Clone the repository:

   ```bash
   git clone https://github.com/webex/webex-byova-gateway-python.git
   cd webex-byova-gateway-python
   ```

2. Create and activate a virtual environment:

   ```bash
   python -m venv venv
   source venv/bin/activate
   ```

   On Windows:

   ```text
   venv\Scripts\activate
   ```

3. Install dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

4. Generate the Python gRPC stubs:

   ```bash
   python -m grpc_tools.protoc \
     -I./proto \
     --python_out=src/generated \
     --grpc_python_out=src/generated \
     proto/*.proto
   ```

The generated `*_pb2.py` and `*_pb2_grpc.py` files are intentionally not committed.

## Configure a Local-Only Run

The checked-in configuration enables gRPC JWT validation but does not contain a datasource
URL. This is intentional for security: the gateway refuses to start with incomplete enabled
JWT configuration.

For a local-only test that is not connected to Webex, edit `config/config.yaml` and set:

```yaml
authentication:
  enabled: false

jwt_validation:
  enabled: false
```

Do not use those settings for a Webex-connected or production endpoint. For end-to-end
testing, configure the registered datasource URL and keep JWT enforcement enabled as
described in [JWT Authentication](JWT_AUTHENTICATION.md).

The default local audio files are included in `audio/`, so no additional media setup is
required for the local connector. See
[Local Audio Connector Configuration](LOCAL_AUDIO_CONFIGURATION.md) for its `agent_id`,
audio path, DTMF behavior, and end-to-end sandbox flow.

## Run the Gateway

With the virtual environment active:

```bash
python main.py
```

The process starts:

- The gRPC server on `localhost:50051`
- The monitoring interface on `http://localhost:8080`

Press `Ctrl+C` to stop the gateway and allow it to clean up active conversations.

## Monitoring Interface

For a local run with dashboard authentication disabled, open:

- Dashboard: `http://localhost:8080`
- Status: `http://localhost:8080/api/status`
- Connections: `http://localhost:8080/api/connections`
- HTTP health: `http://localhost:8080/health`

For the dashboard's Webex OAuth setup and security model, see:

- [Authentication Quick Start](../AUTHENTICATION_QUICKSTART.md)
- [Monitoring Interface](../src/monitoring/README.md)

The dashboard is a development and diagnostic interface. Review the
[Production Readiness Guide](PRODUCTION_READINESS.md) before exposing any administrative
interface in production.

## Test Through a Public Endpoint

BYOVA requires a publicly reachable TLS endpoint on the domain authorized for the Service
App. Use company-owned cloud infrastructure for production and whenever company ownership,
security review, or compliance is required.

For temporary development testing, a tunneling service may be usable if your organization
permits it. For example, with ngrok:

```bash
ngrok config add-authtoken YOUR_AUTHTOKEN
ngrok http --upstream-protocol=http2 50051
```

Use the generated HTTPS URL consistently in both the data-source registration and
`jwt_validation.datasource_url`. Free tunnel URLs may change between runs.

Consumer tunnels are development-only:

- Anyone with the URL can reach the exposed endpoint.
- Do not expose production credentials or caller data.
- Confirm HTTP/2 and bidirectional gRPC behavior before troubleshooting the application.
- Follow your organization's network and data-handling policies.

See [Security Configuration](Security-Configuration.md) for a company-controlled TLS and
load-balancer starting point.

## Troubleshooting

### The Gateway Fails With an Empty Datasource URL

If JWT validation is enabled, `jwt_validation.datasource_url` is required. For local-only
testing, disable JWT validation. For Webex-connected testing, configure the exact registered
URL. See [JWT Authentication](JWT_AUTHENTICATION.md).

### Port 50051 or 8080 Is Already in Use

Find the process using the port:

```bash
lsof -i :50051
lsof -i :8080
```

Stop the conflicting application or change the corresponding port in
`config/config.yaml`.

### Python or Imports Cannot Be Found

Confirm the virtual environment is active:

```bash
echo "$VIRTUAL_ENV"
which python
```

If necessary, recreate it:

```bash
python -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

### Generated Modules Cannot Be Imported

Regenerate the gRPC files:

```bash
python -m grpc_tools.protoc \
  -I./proto \
  --python_out=src/generated \
  --grpc_python_out=src/generated \
  proto/*.proto
```

### Review Logs

The gateway logs to standard output and, when configured, `logs/gateway.log`. The monitoring
application uses `logs/web.log`. Adjust logging levels in `config/config.yaml`; do not enable
unsafe payload or audio logging with customer traffic.

## Related Documentation

- [Configuration](../config/README.md)
- [Local audio connector configuration](LOCAL_AUDIO_CONFIGURATION.md)
- [Testing](TESTING.md)
- [Connector development](../src/connectors/README.md)
- [Return to the project README](../README.md)
