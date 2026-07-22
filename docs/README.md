# Webex Contact Center BYOVA Gateway Documentation

Use this index to find the guide for your current stage. The gateway is functional sample
code, not a managed connector or a production-ready service.

## Evaluate and Onboard

- [Customer Evaluation](CUSTOMER_EVALUATION.md): Determine whether BYOVA and this gateway fit
  an existing voice-agent platform, understand responsibilities, and plan a proof of concept.
- [Official BYOVA Developer Guide](https://developer.webex.com/webex-contact-center/docs/bring-your-own-virtual-agent):
  Current Webex concepts, Service App, data-source, and onboarding guidance.
- [BYOVA with AWS Lex](https://developer.webex.com/webex-contact-center/docs/byova-and-aws-lex):
  Complete Webex Contact Center and AWS Lex walkthrough.

## Develop and Test

- [Local Audio Connector Configuration](LOCAL_AUDIO_CONFIGURATION.md): Validate the gateway
  and a Webex Contact Center sandbox before selecting a voice-agent provider.
- [Local Development](LOCAL_DEVELOPMENT.md): Install, configure a local-only run, start the
  gateway, use the monitoring interface, and troubleshoot development issues.
- [Configuration Reference](../config/README.md): Settings read by the current gateway and
  connectors, including known sample-only placeholders.
- [Testing Guide](TESTING.md): Automated tests, HTTP smoke tests, gRPC health checks, and
  end-to-end validation.
- [Connector Guide](../src/connectors/README.md): Connector interface, available connectors,
  and extension pattern.
- [Monitoring Interface](../src/monitoring/README.md): Dashboard behavior, Webex OAuth, APIs,
  and security considerations.

## Authenticate and Secure

- [gRPC JWT Authentication](JWT_AUTHENTICATION.md): Runtime Webex token validation,
  datasource claims, deployment modes, and troubleshooting.
- [Monitoring Authentication Quick Start](../AUTHENTICATION_QUICKSTART.md): Configure Webex
  OAuth for the development dashboard.
- [Security Configuration](Security-Configuration.md): TLS and load-balancer setup guidance.

## Integrate Providers

- [AWS Lex Configuration](AWS_LEX_CONFIGURATION.md): AWS credentials and Lex connector
  settings.
- [Audio Files](../audio/README.md): Local audio formats and sample media.
- [Protocol Definitions](../proto/README.md): BYOVA and gRPC schema information.

## Prepare for Production

- [Productization and Production Readiness](PRODUCTION_READINESS.md): High availability,
  capacity, observability, alerting, security, testing, incident response, and launch gates.

## Repository Entry Points

- [Project README](../README.md): Overview and quick start.
- [Core Gateway](../src/core/README.md): Core server and routing components.
- [Utilities](../src/utils/README.md): Audio buffer, conversion, recording, and logging helpers.
- [Test Suite Notes](../tests/README.md): Detailed test organization and markers.

## License

[Cisco Sample Code License v1.1](../LICENSE) © 2018 Cisco and/or its affiliates.
