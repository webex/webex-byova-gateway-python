# BYOVA E2E Test Caller

This local tool uses a Python orchestrator and a browser-only Webex Calling SDK
client to call the WxCC extension and inject one prepared caller utterance after
the remote prompt becomes quiet.

## One-time setup

Node.js is only a local build tool for the browser client. Webex Calling itself
runs in Chromium; it does not run in Node. The runner builds that client before
each test, so install Node `20.19+` (or `22.12+`) on the machine running the
tool.

```bash
cd tools/byova_e2e
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python -m playwright install chromium

cd web
npm ci
```

For this macOS POC, `--text` uses the built-in `say` synthesizer with the
installed `Samantha` voice. It does not download a model or contact Hugging
Face. Use `--voice` to select another installed macOS voice, or `--wav` to
inject a local audio fixture.

## Webex Calling and WxCC extension-dialing setup

Complete this setup in the target non-production Webex organization before
authorizing or placing a test call. The OAuth integration authorizes a user; it
does not itself create a Webex Calling line or a route to the contact center.

1. Create a dedicated test caller. Assign it a Webex Calling entitlement that
   supports the Webex App/browser calling client, a Calling location, and an
   internal extension. Ensure browser/WebRTC calling is enabled for that
   Calling user and that it can register a soft-client device.
2. Configure the dedicated caller's Calling location dial plan so that the
   contact-center entry-point extension is an **internal** dialable destination.
   For this environment, use `9999`. Do not substitute a PSTN number for this
   test path.
3. In WxCC, configure the inbound entry point/call queue to receive extension
   `9999` and route it to the intended BYOVA test flow. Confirm the queue's
   assigned number/extension and the flow association before testing.
4. Verify the route manually: sign in as the dedicated caller in a supported
   Webex Calling client and dial `9999`. Confirm that the expected queue and
   BYOVA flow answer the call. Resolve Calling-location, dial-plan, or queue
   routing failures before using the automated caller.
5. Record the test-user email and OAuth client settings in the local `.env`
   file. During `byova-e2e login`, complete consent as that dedicated caller.
   The OAuth access token determines the actual Calling line used for the call;
   `BYOVA_E2E_TEST_USER_EMAIL` is an operator-facing reminder, not an identity
   assertion in the current version.
6. Validate soft-client registration before automation. Sign in as the test
   caller in a supported Webex Calling client, then sign out and back in if the
   client cannot register. A Calling SDK error saying **"unable to find your
   device"** (HTTP 404 from `/devices/<id>/status`) means the test user does
   not have a valid Calling soft-client device registration; fix that
   provisioning state before retrying the E2E caller.

The automated run keeps the destination explicit:

```bash
byova-e2e run --destination 9999 --text 'Hello, this is a BYOVA test.'
```

The value supplied to `--destination` is passed to the authorized caller's
Webex Calling line. Use `9999` only after the internal route above is verified.

## Create the Webex OAuth integration

Create a Webex OAuth **Integration** in the Developer Portal before configuring
the local caller. Use a non-production organization and a dedicated integration
for this test caller; do not reuse a personal development integration.

1. In the Webex Developer Portal, create a new **Integration** named something
   recognizable, such as `BYOVA E2E Test Caller`.
2. Set its redirect URI to exactly:

   ```text
   http://localhost:8765/oauth/callback
   ```

   This must exactly match `BYOVA_E2E_WEBEX_REDIRECT_URI` in `.env`. Use
   `localhost`, not `127.0.0.1`; the Developer Portal configuration for this
   integration accepts the former callback host.
3. Add these OAuth scopes:

   ```text
   spark:xsi
   spark:calls_write
   spark:calls_read
   spark:webrtc_calling
   ```

4. Save the integration. Copy its client ID and client secret directly into the
   local ignored `.env` file. Never commit the secret or include it in a test
   artifact.

The integration identifies this local application. It does **not** choose the
caller identity: the dedicated test user who completes `byova-e2e login` is the
Webex Calling user whose line will place the call.

## Run a test

Copy `.env.example` to `.env`, then fill in the client ID and secret for the
**BYOVA E2E Test Caller** integration. The runner loads that local `.env` file
automatically; it is ignored by Git, and explicit shell values take precedence.

```bash
cd tools/byova_e2e
source .venv/bin/activate
cp .env.example .env
# Edit .env locally; do not commit it.
byova-e2e login
```

`login` prints an authorization URL. Open it in the existing **WxCC Admin**
Chrome profile, sign in as the `BYOVA_E2E_TEST_USER_EMAIL` configured in
`.env`, and approve consent. The local callback must remain
`http://localhost:8765/oauth/callback`, matching the integration configuration.
When `BYOVA_E2E_TEST_USER_EMAIL` is set, the authorization request explicitly
selects an account and supplies that email as the login hint so an existing
administrator session cannot be accepted accidentally.
The returned access and refresh tokens are written to the user-level
`$XDG_STATE_HOME/byova-e2e/oauth-token.json` (or
`~/.local/state/byova-e2e/oauth-token.json`) with owner-only permissions. This
location is shared across repository clones and worktrees. An existing
checkout-local `.state/oauth-token.json` is copied to the shared location on
its next use.

On later runs, the tool uses the saved access token while it is valid. When it
expires, the tool exchanges the saved refresh token for a new token pair and
atomically saves the response, including any rotated refresh token. This keeps
the dedicated test user authorized without another browser consent. A new
`byova-e2e login` is required only if the refresh token expires or is revoked,
or if the OAuth integration credentials change. Set
`BYOVA_E2E_WEBEX_TOKEN_PATH` to an absolute path to override the shared
location. A temporary `BYOVA_E2E_WEBEX_ACCESS_TOKEN` environment value can
instead be used for a single run; because it has no associated refresh token,
it is not persisted.

```bash
byova-e2e run --destination 9999 --text 'Hello, this is a BYOVA test.'
```

The caller normally waits for remote audio activity and then 750 ms of quiet
before it injects the utterance. Some queue routes start in silence. If no
remote speech is observed, the caller injects after 10 seconds by default; set
`--initial-silence-fallback-seconds 0` to require the prompt-based gate. The
artifact records which gate sent the utterance. Run artifacts are written to
`.artifacts/`; use them with the gateway logs and recordings for post-call
diagnosis.

### Run a bounded natural-pause scenario

Use repeated `--text-segment` values to render one deterministic caller WAV
with exact sample-level silence between phrases. The following command inserts
1.8 seconds of silence: one second for the gateway VAD end-silence threshold
and 800 ms inside the default one-second GECX resume grace.

```bash
byova-e2e run \
  --destination 9999 \
  --text-segment "I'd like to book" \
  --text-segment "a room in San Jose" \
  --segment-pause-ms 1800 \
  --remote-prompt-occurrence 2 \
  --require-remote-response \
  --response-timeout-seconds 30
```

With `--require-remote-response`, the run fails unless remote audio begins
after caller injection and subsequently becomes quiet. The artifact records
the segment count, inserted pause, response observation, and measured response
latency. It also records UTC receipt time for every browser event plus the
overall UTC run window, providing an exact interval for gateway and CES log
correlation. Confirm that both segments formed one CES transcript and one WxCC
START/END boundary pair.

For Webex Contact Center entry points that play ringback before the virtual
agent greeting, `--remote-prompt-occurrence 2` waits for the second completed
remote-audio epoch. This prevents the caller fixture from being injected
between ringback and creation of the BYOVA conversation.

Live runs use headless Chromium by default, so automated calls do not open a
browser window over other work. Add `--headed` only when interactive browser
media debugging is required.

## Define tests in JSON

Each version 1 test contains one audio action followed by one expectation. A
`speak` action accepts either `text` or `segments` plus `pauseMs`; a `play`
action accepts a WAV `path` relative to the config file. Test plans follow
Playwright conventions: top-level `use` defaults, named `tests`, ordered
`steps`, and explicit `expect` assertions. Reference
`config/byova-e2e.schema.json` for editor validation and autocomplete.

```json
{
  "$schema": "./byova-e2e.schema.json",
  "version": 1,
  "use": {
    "headless": true,
    "responseTimeoutSeconds": 30
  },
  "tests": [
    {
      "id": "request-response",
      "title": "receives a complete virtual-agent response",
      "steps": [
        {
          "name": "Speak one request",
          "action": "speak",
          "text": "Please help me with my request."
        },
        {
          "name": "Expect one complete response",
          "expect": {
            "outcome": "response",
            "responsePrompts": 1
          }
        }
      ]
    }
  ]
}
```

Validate and list the plan without authenticating or placing a call:

```bash
byova-e2e validate --config path/to/connector.spec.json --list
```

Then run one selected test with Playwright-style `--config` selection:

```bash
byova-e2e run \
  --destination 9999 \
  --config path/to/connector.spec.json \
  --test request-response
```

Top-level `use` values apply to every test. A test may define its own `use`
object to override those defaults. Explicit CLI options have final precedence,
which is useful for a one-off timeout or headed debugging run. The loader
rejects unsupported versions, duplicate test IDs, invalid step order, and
unknown fields before it obtains a token or places a call.

The completed artifact records the selected test, config path and SHA-256,
expected outcome, completed remote-prompt count, Calling SDK disconnect
cause/code, whether the caller requested that disconnect, and the exact UTC
event window. The config hash ties live evidence to the exact plan contents.

For custom fixtures, `--expect-outcome response|session-end|transfer` enables
the same assertions without using a named test. Flows that guarantee a
minimum connected interval after transfer can add
`--connected-observation-seconds`; it is disabled by default because queue and
agent-availability behavior differs after WxCC accepts the transfer event.

## Safety boundaries

- The local server listens only on loopback and suppresses HTTP request logs so
  the access token is not printed.
- `run` deliberately dials only the destination passed for that invocation.
- The browser client measures remote audio activity with Web Audio; it does not
  transcribe, store, or upload remote prompt audio.
- This tool records its own timing events and audio hash, not call recordings or
  OAuth tokens.
