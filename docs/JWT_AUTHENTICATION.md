# gRPC JWT Authentication

The gateway validates signed JWTs on inbound gRPC requests from Webex Contact Center. This
protects the BYOVA data plane and is separate from the Webex OAuth login used by the optional
monitoring dashboard.

For dashboard authentication, see
[Authentication Quick Start](../AUTHENTICATION_QUICKSTART.md) and the
[Monitoring Interface documentation](../src/monitoring/README.md).

## What the Gateway Validates

When validation is enabled, the gateway:

- Reads a token from the gRPC `authorization` metadata entry.
- Accepts `Bearer <JWT_TOKEN>` and raw-token formats.
- Allows only the Webex identity-broker issuers listed in
  `src/auth/jwt_validator.py` before fetching signing keys.
- Verifies the RS256 signature and expiration.
- Requires nonempty `aud`, `sub`, and `jti` claims.
- Requires the datasource URL and schema claims to match the configured values.
- Caches identity-broker public keys for the configured duration.

With enforcement enabled, missing or invalid credentials are rejected before the RPC reaches
the gateway service.

## Configuration

Configure `jwt_validation` in `config/config.yaml`:

```yaml
jwt_validation:
  enabled: true
  enforce_validation: true
  datasource_url: "https://your-gateway.example.com:443"
  datasource_schema_uuid: "5397013b-7920-4ffc-807c-e8a3e0a18f43"
  cache_duration_minutes: 60
```

The gateway fails to start when validation is enabled and `datasource_url` is empty.

### Datasource URL

`datasource_url` must exactly match the URL registered through the
[Webex Data Sources API](https://developer.webex.com/webex-contact-center/docs/api/v1/data-sources).
The runtime token contains that URL as a claim, and the validator performs a
character-for-character comparison.

These values are different:

```text
https://gateway.example.com
https://gateway.example.com:443
```

Copy the registered value rather than reconstructing it. Use the same URL when a temporary
development endpoint changes.

### Datasource Schema UUID

The standard Voice Virtual Agent schema UUID used by this sample is:

```text
5397013b-7920-4ffc-807c-e8a3e0a18f43
```

It corresponds to the Voice Virtual Agent schema in the
[Webex dataSourceSchemas repository](https://github.com/webex/dataSourceSchemas). Change it
only when intentionally targeting a different approved schema.

### Supported Issuers

The current implementation accepts:

- `https://idbrokerbts.webex.com/idb`
- `https://idbrokerbts-eu.webex.com/idb`
- `https://idbroker.webex.com/idb`
- `https://idbroker-eu.webex.com/idb`
- `https://idbroker-b-us.webex.com/idb`
- `https://idbroker-ca.webex.com/idb`

`JWTValidator.VALID_ISSUERS` in `src/auth/jwt_validator.py` is the source of truth for the
running code. Treat issuer additions as security-sensitive code changes.

## Deployment Modes

### Local-Only Development

For a local test that cannot receive a Webex token:

```yaml
jwt_validation:
  enabled: false
```

Do not expose that configuration to Webex or use it in production.

### Validation Observation

For a controlled nonproduction rollout, validation can run without rejecting invalid tokens:

```yaml
jwt_validation:
  enabled: true
  enforce_validation: false
  datasource_url: "https://your-test-gateway.example.com:443"
```

This mode logs validation failures but permits the request. Protect access to the logs, and
use this mode only for a time-bounded validation exercise.

### Production

```yaml
jwt_validation:
  enabled: true
  enforce_validation: true
  datasource_url: "https://your-production-gateway.example.com:443"
  datasource_schema_uuid: "5397013b-7920-4ffc-807c-e8a3e0a18f43"
  cache_duration_minutes: 60
```

Production deployments should also enforce TLS, restrict network paths, monitor validation
failures, and alert on identity-key refresh failures. See
[Security Configuration](Security-Configuration.md) and
[Production Readiness](PRODUCTION_READINESS.md).

## Troubleshooting

### Gateway Fails to Start

If validation is enabled, configure a nonempty datasource URL. The value must be the actual
registered endpoint, not a placeholder.

### Missing JWT Token

- Confirm that the data source is registered and active.
- Confirm that the request reaches the gateway through the expected Webex path.
- Check for an `authorization` metadata value.
- Verify that a proxy or load balancer preserves gRPC metadata.

### Invalid Signature or Public-Key Fetch Failure

- Confirm outbound HTTPS access to the relevant Webex identity broker.
- Confirm system time is synchronized.
- Check the issuer and key-refresh logs.
- Do not add an issuer simply to bypass a validation failure.

### Invalid Issuer

Compare the token issuer with `JWTValidator.VALID_ISSUERS`. The validator checks the issuer
before making a key request to prevent arbitrary key-fetch URLs.

### Datasource Claims Validation Failed

- Copy the exact registered datasource URL into the configuration.
- Check whether the registered URL includes `:443` or a trailing path.
- Confirm the token schema UUID matches the configured Voice Virtual Agent schema.

### Expired Token

Confirm system clock synchronization. If Webex continues to send expired tokens, preserve a
tracking ID and timestamp and escalate through the appropriate Webex support channel.

## Related Documentation

- [BYOVA customer evaluation](CUSTOMER_EVALUATION.md)
- [Configuration reference](../config/README.md)
- [Local development](LOCAL_DEVELOPMENT.md)
- [Return to the project README](../README.md)
