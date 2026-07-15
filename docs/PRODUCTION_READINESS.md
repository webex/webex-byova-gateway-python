# Productization and Production Readiness Guide

## Purpose and scope

This repository is a functional BYOVA gateway example. It demonstrates the Webex
Contact Center gRPC contract, connector routing, JWT validation, health checks, and a
development monitoring interface. It is not a turnkey production service and has not
been capacity-certified for a particular call volume.

This guide is for engineering, platform, security, and operations teams after they have
successfully validated their BYOVA integration in a proof of concept. Customer evaluation,
compatibility questions, Webex onboarding, and the proof-of-concept path are covered in the
[Customer Evaluation Guide](CUSTOMER_EVALUATION.md).

The sections below describe the engineering, security, reliability, and operating
capabilities that a customer or implementation partner should add before using a derivative
of this gateway in a high-volume contact center. This is a requirements and planning guide,
not a supported deployment architecture or a substitute for the responsible organization's
architecture, security, privacy, and operational reviews.

CPU, memory, worker, stream, and session values in the sample configuration are runtime
defaults, not production sizing recommendations. Production values must be established
by representative load and failure testing.

## Production readiness at a glance

The production service should provide all of the following:

- Multiple instances across independent failure zones, with no single-instance dependency.
- Capacity validated against peak concurrent calls, call-arrival bursts, and vendor latency.
- Structured logs, metrics, and distributed traces correlated by tracking identifiers.
- Service-level objectives (SLOs), actionable alerts, PagerDuty or equivalent routing, and
  owned runbooks.
- Explicit timeouts, bounded retries, backpressure, circuit breakers, and graceful draining.
- Enforced authentication, encrypted transport, least-privilege access, and managed secrets.
- Privacy controls for caller data, transcripts, DTMF, tokens, and recorded audio.
- Automated builds, security scanning, staged releases, rollback, and disaster recovery.
- A staffed service ownership model with incident response and change-management processes.

## Current example versus a production service

| Area | Current example | Production requirement |
| --- | --- | --- |
| Metrics | Configuration includes `metrics_enabled`, and the Prometheus client is a dependency, but the gateway does not currently publish an instrumented metrics endpoint. | Export application, connector, runtime, and infrastructure metrics to the company's monitoring platform. |
| Logging | Human-readable console and local file logs. Some messages include a conversation ID. | Structured JSON logs with consistent tracking IDs, safe fields, centralized collection, retention, and access controls. |
| Tracing | No end-to-end distributed tracing. | OpenTelemetry or an equivalent standard across gRPC handling, routing, and vendor calls. |
| Alerting | No production alert routing or on-call integration. | SLO-based alerts routed to PagerDuty or the company's on-call platform with escalation policies and runbooks. |
| State | Active conversations, recent events, and dashboard history are held in process memory. | Define reconnect and failover semantics; externalize the state that must survive instance loss or use a deliberately tested affinity strategy. |
| Capacity | The gRPC thread pool and concurrent-stream settings are hard-coded. Sample session limits are not a validated capacity model. | Configurable limits established through load tests, with admission control, autoscaling, and headroom. |
| Health | gRPC health primarily reflects whether agents are registered. The HTTP endpoint is a simple process health response. | Separate startup, liveness, readiness, and dependency health; readiness must consider draining, saturation, and critical connector availability. |
| Deployment | A single Python process also starts a Flask development monitoring thread. | Independently operable workloads, production process servers, immutable artifacts, multi-zone placement, and controlled rollout. |
| Transport | The application binds an insecure gRPC port and relies on deployment infrastructure for TLS. | TLS 1.2 or later on every untrusted hop, verified HTTP/2 behavior, certificate automation, and documented trust boundaries. |
| Operations | Local dashboard and recent in-memory events aid development. | Central dashboards, SLOs, alerts, runbooks, incident command, support ownership, and audit history. |

The sections below turn these gaps into a production program.

## 1. Establish service ownership and reliability objectives

Before choosing infrastructure, identify the business impact and the team that owns the
gateway in production.

### Required ownership decisions

- Name a service owner, engineering owner, security owner, and an operational owner with
  on-call coverage aligned to the service's hours and business impact.
- Define which team owns each connector and each upstream virtual-agent dependency.
- Document the boundary between the company, Webex Contact Center, the cloud platform,
  and the virtual-agent vendor.
- Define support tiers, escalation paths, maintenance windows, and change approvers.
- Create a service catalog entry containing dashboards, logs, traces, deployment links,
  PagerDuty service, runbooks, dependency owners, and architecture documentation.

### Define service-level indicators

At minimum, measure:

- Gateway availability: valid RPCs that receive a usable response rather than an
  infrastructure or gateway error.
- Session-start success: conversations that start and reach the selected connector.
- Turn success: caller turns that produce a valid response or an intentional terminal event.
- Time to first virtual-agent audio: from caller turn completion to the first response audio.
- End-to-end turn latency: from accepted caller input to the final response event.
- Session completion quality: normal completion, human escalation, caller abandonment,
  timeout, connector failure, and forced cleanup.
- Reconnection success, if reconnection is a supported behavior.

Set SLOs and an error-budget policy for these indicators. Availability and latency targets
must reflect the contact center's business requirements and the dependencies' own SLOs.
Do not adopt generic targets without validating that the complete call path can meet them.

## 2. Design for high availability and horizontal scale

### Deployment topology

- Run multiple gateway instances across at least two independent failure zones.
- Place instances behind a production load balancer or ingress that explicitly supports
  long-lived bidirectional gRPC streams over HTTP/2.
- Keep application instances private where possible. Expose only the load balancer and
  required administrative endpoints.
- Isolate the operational dashboard from the public gRPC data plane. Prefer a separate
  administrative service protected by company SSO, role-based access, and network policy.
- Ensure a failure in the dashboard or telemetry exporter cannot terminate or starve call
  processing.

### Conversation state and routing

The sample stores `ConversationProcessor` and connector session state in memory. A stream
continues on its current instance, but a reconnect or instance failure can lose that state.
Productization therefore requires an explicit decision:

1. Make reconnectable state external and safely reconstruct connector sessions on another
   instance; or
2. Use session affinity for reconnects, accept that instance loss terminates affected calls,
   and document and test that failure behavior.

Do not externalize raw streaming audio by default. Persist only the minimum state needed for
the chosen recovery model, protect it as customer data, and apply short, documented TTLs.
Prevent simultaneous ownership of the same conversation by using idempotency keys, leases,
or another concurrency-control mechanism.

### Capacity model

Model capacity from traffic measurements rather than configuration defaults:

```text
peak concurrent sessions = peak session starts per second
                           x average virtual-agent session duration
                           x burst and safety factor
```

Also model the number of simultaneous turns, audio bitrate, vendor response time, TLS and JWT
cost, connection churn, reconnect storms, and telemetry volume. Test at expected peak, peak
plus headroom, and instance-loss conditions.

Autoscaling should consider active streams, available session slots, worker/queue saturation,
memory, and connector throttling. CPU alone is not sufficient for long-lived streaming calls.
Keep reserve capacity so losing a zone or deploying a new version does not exhaust the fleet.

### Runtime and connector concurrency

The current synchronous gRPC server uses a thread pool, and the router can share a connector
instance across multiple agents and conversations. Before raising concurrency:

- Audit all conversation maps, monitoring collections, audio buffers, connector clients, and
  session managers for concurrent access and race conditions.
- Require connector implementations to document and test their thread-safety model.
- Keep per-conversation state isolated; protect genuinely shared state with appropriate
  synchronization and avoid holding locks during network or audio operations.
- Profile blocking vendor calls and CPU-heavy audio conversion. Use bounded pools, processes,
  or an asynchronous gRPC design where benchmark evidence shows they are needed.
- Run race, cancellation, and cleanup tests with many simultaneous streams. Confirm that one
  slow connector call cannot consume every worker and block unrelated conversations.

### Admission control and graceful lifecycle

- Enforce configurable per-instance and fleet-wide concurrency limits.
- Apply per-tenant and per-connector quotas so one customer or dependency cannot exhaust the
  shared fleet.
- Reject overload quickly with an intentional gRPC status instead of accepting work that
  will time out later.
- Bound all internal queues and audio buffers.
- On shutdown or deployment, fail readiness first, stop accepting new calls, allow existing
  streams to drain for a defined maximum period, then close remaining sessions cleanly.
- Align application drain time with load-balancer deregistration delay and orchestrator
  termination grace periods.
- Test rolling deployments while the system is carrying representative calls.

## 3. Add production metrics

Expose metrics in Prometheus or OpenTelemetry format and send them to the company's durable
monitoring platform. Metrics must remain useful across many instances and deployments.

### Gateway and gRPC metrics

- Active, opening, completed, cancelled, and rejected streams.
- RPC request count and duration by method and gRPC status.
- Session starts, active sessions, duration, reconnects, and forced cleanup.
- Caller turns and response turns.
- Time to first virtual-agent audio and total turn latency.
- Bytes and audio duration received and sent.
- Invalid messages, protocol errors, stream cancellations, and deadline expirations.
- Human escalation attempts, successes, failures, and time to escalation.
- Session outcomes by a bounded outcome set.

### Connector metrics

- Operation count, error rate, and latency by connector and operation.
- Connection/setup failures, authentication failures, throttling, and vendor error category.
- Retry count, circuit-breaker state, timeout count, and dependency availability.
- Vendor response latency and time to first audio.
- Active vendor sessions and orphaned-session cleanup.
- Audio-buffer depth, dropped audio, and buffer underruns/overruns where applicable.

### Runtime and infrastructure metrics

- CPU, memory, file descriptors, threads, network throughput, and connection count.
- Worker utilization, queue depth, rejected work, and configured versus available capacity.
- Process restarts, out-of-memory kills, deployment version, and instance readiness.
- Load-balancer target health, connection errors, TLS errors, and response codes.
- External state-store latency, errors, capacity, and expiration behavior if one is used.

### Authentication and configuration metrics

- JWT validation success and failure by a bounded reason category.
- Identity public-key fetch failures, refresh latency, and cache age.
- Certificate expiry and rotation failures.
- Configuration load/reload failures and invalid connector definitions.

Never put a conversation ID, tracking ID, caller identifier, organization ID, or other
unbounded value into a metric label. These create high cardinality and can expose customer
data. Use metrics for aggregation and logs or traces for individual-call investigation.

## 4. Implement structured logging and tracking IDs

Use structured JSON logs written to standard output and collected by the platform. Local
rotating files should not be the authoritative production log store.

### Correlation model

For every RPC and conversation:

- Accept an approved inbound tracking or correlation ID from gRPC metadata when present.
- Validate its format and length. Generate a new cryptographically random ID when absent.
- Carry the ID through the gRPC interceptor, gateway server, conversation processor,
  router, and connector.
- Propagate it to vendor requests using the vendor's supported request metadata or headers.
- Include OpenTelemetry `trace_id` and `span_id` when tracing is enabled.
- Return a safe tracking ID in response metadata or trailers when the protocol permits it,
  so support teams can correlate both sides of a failure.

Recommended event fields include:

```text
timestamp, severity, service, environment, version, instance_id,
event_name, message, tracking_id, trace_id, span_id, conversation_id,
rpc_session_id, connector, virtual_agent_id, rpc_method, grpc_status,
session_outcome, duration_ms, retry_count, error_type
```

Conversation and organization identifiers should be pseudonymized or tokenized if operators
do not need the raw value. Use RFC 3339 UTC timestamps and consistent event names and error
categories. Log state transitions once at the correct severity rather than emitting entire
request or response objects.

### Sensitive-data rules

Production logs must not contain:

- JWTs, OAuth tokens, API keys, cookies, or authorization metadata.
- Raw audio, transcripts, or prompt/response content unless a separately approved and
  access-controlled diagnostic workflow requires it.
- DTMF digits, because callers may enter account or payment information.
- Full caller identifiers or unnecessary customer profile data.
- Vendor payloads that may contain personal or regulated data.

Add automated redaction and tests for secrets and personal data. Define retention by data
class and environment, encrypt logs in transit and at rest, audit access, and provide a
documented deletion process. Debug logging must be time-bounded, authorized, and safe to
enable on a subset of instances without exposing caller content.

## 5. Add distributed tracing

Instrument the gateway with OpenTelemetry or the company's standard tracing framework.
Create spans for:

- Authentication and JWT public-key lookup.
- `ListVirtualAgents` and `ProcessCallerInput` stream lifecycle.
- Conversation start, caller turn, connector routing, vendor request, response conversion,
  escalation, and cleanup.
- State-store operations and retry attempts.

Propagate W3C Trace Context where dependencies support it. Use span links or events for a
long-lived stream rather than one unbounded, high-volume span containing every audio chunk.
Sample successful traffic at a controlled rate while retaining errors and unusually slow
transactions. Apply the same sensitive-data restrictions used for logs.

## 6. Build actionable dashboards and on-call alerting

### Dashboards

Maintain at least three views:

1. **Service overview:** traffic, availability, error-budget burn, latency percentiles,
   active calls, call outcomes, deployments, and dependency health.
2. **Capacity:** active versus allowed sessions, workers, queue depth, memory, network,
   autoscaling state, and zone distribution.
3. **Connector detail:** request rate, errors, throttling, timeouts, latency, circuit state,
   and escalation outcomes for each vendor.

Operators must be able to filter by environment, region, zone, version, connector, RPC
method, and bounded error category. Add deployment and configuration-change annotations.

### PagerDuty or equivalent integration

Create a dedicated service in PagerDuty or the company's standard on-call platform, owned by
the team operating the gateway. Configure:

- Primary and secondary on-call schedules and a management escalation path.
- Event deduplication, grouping, acknowledgement, and automatic resolution.
- Links from every page to the relevant dashboard, logs, traces, deployment, and runbook.
- A tested path for the monitoring platform and critical vendor alerts to create incidents.
- Quarterly contact and escalation-policy reviews.

Page on user impact or imminent loss of capacity, not every internal error. Good paging
signals include:

- Fast or slow SLO error-budget burn for gateway availability or session-start success.
- No ready instances in a region or insufficient capacity after loss of an instance or zone.
- Sustained error or timeout rate on a critical connector.
- Severe time-to-first-audio or turn-latency degradation.
- Session count near the safe limit with rejected calls or saturated workers/queues.
- A growing number of stuck or orphaned conversations.
- Widespread JWT validation or identity-key refresh failure.
- Imminent certificate expiry when automated renewal has failed.

Use lower-severity notifications or tickets for single-instance restarts, brief dependency
errors, capacity trends, and non-urgent certificate warnings. Derive thresholds from SLOs,
capacity tests, and real baselines; avoid arbitrary static thresholds.

Every paging alert needs a runbook covering impact, confirmation queries, dependencies,
safe mitigation, rollback, escalation, customer communication, and recovery verification.
Test alerts end to end before launch and during regular game days.

## 7. Engineer dependency failure handling

Every connector and network call must define:

- Connection, request, idle-stream, and total-operation deadlines.
- Which failures are retryable and which are terminal.
- A small retry budget with exponential backoff and jitter.
- Idempotency behavior for conversation start, end, and escalation.
- Circuit-breaker thresholds and half-open recovery behavior.
- Per-connector concurrency limits and rate-limit handling.
- A safe caller experience when the vendor is unavailable, including human escalation or
  controlled termination as agreed with the contact-center team.

Retries must fit within the caller interaction deadline and must not amplify an outage.
Propagate cancellation and deadlines so abandoned calls stop consuming vendor and gateway
resources. Clean up vendor sessions on all terminal paths, including client cancellation,
instance shutdown, timeouts, and partial failures.

## 8. Strengthen health checks

Expose distinct checks for different consumers:

- **Startup:** configuration is valid, required secrets are available, and connectors can
  initialize.
- **Liveness:** the process is responsive and not deadlocked. Do not fail liveness solely
  because a vendor is unavailable, or the orchestrator may create a restart storm.
- **Readiness:** the instance is not draining or saturated and can accept a new call.
- **Dependency health:** connector authentication, state store, identity-key service, and
  other required dependencies are functioning within a recent time window.

Avoid making every health probe perform a paid or expensive vendor transaction. Combine
passive health from actual calls with controlled synthetic checks. The load balancer should
use readiness, while operators and dashboards should see dependency detail separately.

## 9. Harden security and privacy

Use [Security Configuration](Security-Configuration.md) as a starting point, then complete a
formal threat model and security review.

### Data plane

- Enforce JWT validation in production and fail startup on unsafe or incomplete settings.
- Validate issuer, audience, expiry, datasource URL, schema UUID, and all required claims.
- Terminate TLS only at an approved trust boundary and encrypt traffic on additional
  untrusted hops. Verify HTTP/2 and certificate hostname validation end to end.
- Apply request/message size limits, stream limits, rate limits, and malformed-input tests.
- Restrict network paths to expected Webex, vendor, identity, and telemetry endpoints.

### Administrative plane

- Put dashboards and debug endpoints behind company SSO, RBAC, MFA, and network controls.
- Remove or disable development/test endpoints in production.
- Do not expose active-session details broadly; treat them as customer operational data.
- Record administrative access and security-relevant configuration changes in an audit log.

### Secrets and software supply chain

- Store secrets in the platform's managed secret service, never in YAML, images, or logs.
- Use workload identity or short-lived credentials instead of static cloud access keys.
- Rotate credentials and certificates automatically and test rotation without call impact.
- Pin and scan dependencies, generate an SBOM, sign build artifacts, scan container images,
  and remediate critical vulnerabilities within an agreed SLA.
- Run as a non-root user with a read-only filesystem and minimal Linux capabilities when
  containerized.

### Audio and regulated data

Disable audio recording by default in production. If recording is required, obtain privacy
and legal approval and define consent, purpose, residency, encryption, access, retention,
deletion, and audit requirements. Store recordings outside the application container in an
approved encrypted service. Account for PCI DSS, HIPAA, GDPR, regional privacy rules, or
other obligations that apply to the contact center.

## 10. Establish a production delivery process

- Build immutable, versioned artifacts in CI from reviewed source.
- Run formatting, linting, type checks, unit tests, integration tests, dependency scans,
  secret scans, and artifact/image scans on every change.
- Generate gRPC code deterministically and detect incompatible protocol changes.
- Validate configuration against a typed schema and reject unknown or unsafe values.
- Promote the same artifact through development, load, staging, canary, and production.
- Use canary or progressive delivery with automated health and SLO checks.
- Keep a tested one-step rollback path, including configuration rollback.
- Separate connector feature flags and emergency disable controls from code deployment.
- Require peer review and record who approved and deployed each production change.

Deployment tests must include active streams. A successful process start or unary health
check does not prove that long-lived audio calls survive the rollout.

## 11. Validate performance and resilience

Create an automated load harness that behaves like real Webex traffic: long-lived
bidirectional gRPC streams, representative audio cadence and size, DTMF and event traffic,
JWT validation, connector calls, escalation, cancellation, and reconnect behavior.

Test all of the following:

- Expected peak, peak plus safety margin, sudden arrival bursts, and sustained soak traffic.
- One instance and one zone lost at peak traffic.
- Slow, throttled, unavailable, and partially failing connector dependencies.
- Expired/invalid JWTs and identity public-key refresh failure.
- Network latency, packet loss, disconnects, and reconnect storms.
- Rolling deployments, certificate rotation, secret rotation, and autoscaling events.
- Stuck streams, callers that never send a terminal event, and maximum session duration.
- Telemetry backend failure without impact to call handling.
- Disk, memory, file descriptor, thread, and network exhaustion.

Measure caller-visible outcomes as well as server throughput. Confirm that the service sheds
load predictably, recovers without manual data repair, and does not leak sessions or memory
during a long soak test.

Capacity-test reports should record artifact version, instance shape, replica count, limits,
traffic model, connector behavior, results, bottlenecks, and approved operating ceiling.
Repeat tests after changes to audio handling, connectors, concurrency, telemetry, runtime,
or infrastructure.

## 12. Prepare incident response and disaster recovery

Create version-controlled runbooks for at least:

- High error rate or slow response.
- Connector outage, throttling, or credential failure.
- Capacity saturation and rejected calls.
- Stuck/orphaned sessions or memory growth.
- JWT validation or identity-key failure.
- Certificate expiry or TLS failure.
- Bad deployment or configuration change.
- Regional or state-store failure.
- Suspected data exposure or compromised credential.

Define recovery time and recovery point objectives based on business requirements. Back up
only durable data that is actually required; ephemeral audio-stream state may not be
recoverable. Replicate configuration and required state to the recovery location, document
DNS/load-balancer failover, and test restoration and regional failover on a schedule.

After incidents, preserve a timeline using tracking IDs, complete a blameless review, assign
corrective actions, and verify those actions through tests or game days.

## 13. Control cost and data retention

Forecast and monitor cost per concurrent session, call minute, and completed conversation.
Include compute, load balancing, NAT/network transfer, vendor usage, state storage, metrics,
logs, traces, and approved audio storage. Set budgets and anomaly alerts.

Telemetry volume can be substantial for audio workloads. Use event-based logging, bounded
cardinality, trace sampling, and retention tiers. Cost controls must never silently remove
the minimum data required to detect incidents or investigate customer impact.

## Recommended implementation sequence

### Phase 1: Define the production contract

- Confirm the proof-of-concept results and documented Webex, customer, and provider
  responsibility boundaries.
- Assign owners and dependency boundaries.
- Define session/reconnect/failover semantics.
- Define SLIs, SLOs, error budgets, data classifications, and retention.
- Produce a threat model and target deployment architecture.

### Phase 2: Make the service observable and bounded

- Add tracking-ID propagation, structured safe logging, metrics, and traces.
- Add configurable concurrency limits, bounded buffers, deadlines, and admission control.
- Split startup, liveness, readiness, and dependency health.
- Create dashboards and capacity baselines.

### Phase 3: Add resilience and secure delivery

- Deploy across failure zones with drain-aware rolling updates.
- Implement the chosen session-state model, connector isolation, retries, and circuit breakers.
- Harden authentication, TLS, secrets, admin access, and the software supply chain.
- Build CI/CD, canary, rollback, and configuration validation.

### Phase 4: Operationalize

- Create the PagerDuty or equivalent on-call service, alert policies, escalation paths, and
  runbooks.
- Run peak, soak, dependency-failure, and zone-failure tests.
- Train on-call responders and conduct game days.
- Complete security, privacy, architecture, and business launch reviews.

## Production launch checklist

The service is not ready for production until the customer or implementation partner can
answer **yes** to every applicable item:

- [ ] The BYOVA proof of concept is complete and its functional, caller-experience, and
  support-boundary results are accepted.
- [ ] A named team owns the service and provides the required on-call coverage.
- [ ] SLIs, SLOs, error budgets, and dependency objectives are approved.
- [ ] Representative peak, burst, soak, and failure tests establish a safe capacity limit.
- [ ] The fleet survives an instance and zone loss while carrying peak traffic.
- [ ] Concurrency limits, backpressure, bounded buffers, deadlines, and graceful draining work.
- [ ] Reconnect and instance-loss behavior are documented and tested.
- [ ] Metrics, structured logs, tracking IDs, and traces cover the full request path.
- [ ] Dashboards and PagerDuty or equivalent alerts have been tested end to end.
- [ ] Every paging alert links to an owned and exercised runbook.
- [ ] Readiness reflects draining and capacity; dependency failures are visible separately.
- [ ] JWT validation and TLS are enforced and certificate/key rotation has been tested.
- [ ] Secrets use managed storage and short-lived/workload credentials where possible.
- [ ] Debug/test endpoints and production audio logging are disabled or separately approved.
- [ ] Privacy, security, compliance, retention, and data-residency reviews are complete.
- [ ] CI/CD produces immutable scanned artifacts with canary and rollback support.
- [ ] Vendor quotas, throttling behavior, outage handling, and support escalation are documented.
- [ ] Disaster recovery meets approved recovery objectives and has been exercised.
- [ ] Cost budgets, anomaly detection, and telemetry retention are in place.
- [ ] Launch approval and residual risks are recorded by the accountable owners.
