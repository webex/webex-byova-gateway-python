"""Python-owned browser lifecycle and prompt-timed call orchestration."""

from __future__ import annotations

import subprocess
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from .gateway_events import GatewayEventError, GatewayEventObserver
from .models import (
    ExpectedOutcome,
    RunAction,
    RunConfig,
    RunEvent,
    RunExpectation,
)
from .server import LocalRunServer
from .state import PromptGate


class RunFailure(RuntimeError):
    """An expected E2E caller failure suitable for a non-zero CLI exit."""

    def __init__(self, message: str, events: list[RunEvent] | None = None) -> None:
        super().__init__(message)
        self.events = events or []


@dataclass(frozen=True)
class ResponseObservation:
    """Remote prompt and disconnect evidence collected after caller injection."""

    prompt_count: int
    latency_seconds: float
    disconnect_event: RunEvent | None = None


class BrowserRunner:
    """Run one Call SDK browser client while retaining all policy in Python."""

    def __init__(self, tool_root: Path, config: RunConfig) -> None:
        self.tool_root = tool_root
        self.config = config
        self.events: list[RunEvent] = []
        self.browser_diagnostics: list[str] = []
        self._gateway_events: GatewayEventObserver | None = None

    def run(self) -> dict[str, Any]:
        started_at_utc = datetime.now(timezone.utc).isoformat()
        static_root = self._build_frontend()
        server = LocalRunServer(static_root, self.config)
        server.start()
        final_reason = "unknown"
        try:
            self._begin_gateway_observation()
            with sync_playwright() as playwright:
                browser = None
                context = None
                try:
                    browser = playwright.chromium.launch(
                        headless=self.config.headless,
                        args=[
                            "--use-fake-ui-for-media-stream",
                            "--use-fake-device-for-media-stream",
                        ],
                    )
                    context = browser.new_context(permissions=["microphone"])
                    page = context.new_page()
                    page.on(
                        "console",
                        lambda message: self._record_console(
                            message.type, message.text
                        ),
                    )
                    page.on(
                        "pageerror",
                        lambda error: self._record_console("pageerror", str(error)),
                    )
                    page.on("response", self._record_failed_response)
                    page.goto(server.url, wait_until="networkidle")
                    page.click("#start-calling-test")
                    self._wait_for(
                        server, lambda event: event.name == "frontend_ready", 20
                    )
                    self._command(page, "dial")
                    deadline = time.monotonic() + self.config.call_timeout_seconds
                    self._wait_for_established(
                        server,
                        self._bounded_timeout(
                            self.config.prompt_timeout_seconds, deadline
                        ),
                    )
                    if self.config.steps:
                        finish_result = self._execute_steps(
                            server, page, deadline
                        )
                    else:
                        self._wait_for_prompt_end(server, page, deadline)
                        injection_finished = self._wait_for(
                            server,
                            lambda event: event.name == "injection_finished",
                            self._bounded_timeout(30, deadline),
                        )
                        finish_result = self._finish_call(
                            server,
                            page,
                            deadline,
                            injection_finished,
                        )
                    final_reason = str(finish_result["completion_reason"])
                finally:
                    # A crashed browser can make close() fail. Preserve the original
                    # RunFailure so the CLI can write its diagnostic artifact.
                    if context is not None:
                        with suppress(PlaywrightError):
                            context.close()
                    if browser is not None:
                        with suppress(PlaywrightError):
                            browser.close()
        except RunFailure as error:
            diagnostics = "; ".join(self.browser_diagnostics[-8:])
            event_history = list(self.events)
            if diagnostics:
                raise RunFailure(
                    f"{error}. Browser diagnostics: {diagnostics}", event_history
                ) from error
            raise RunFailure(str(error), event_history) from error
        except PlaywrightError as error:
            raise RunFailure(
                f"Browser automation failed: {error}", list(self.events)
            ) from error
        finally:
            server.close()

        return {
            "started_at_utc": started_at_utc,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            "completion_reason": final_reason,
            "remote_response_observed": finish_result["remote_response_observed"],
            "remote_response_latency_seconds": finish_result[
                "remote_response_latency_seconds"
            ],
            "observed_remote_prompt_count": finish_result[
                "observed_remote_prompt_count"
            ],
            "disconnect": finish_result["disconnect"],
            "gateway_terminal_event": finish_result.get(
                "gateway_terminal_event"
            ),
            "steps": finish_result.get("steps", []),
            "events": [
                {
                    "name": event.name,
                    "timestamp": event.timestamp,
                    "received_at_utc": event.received_at_utc,
                    "details": event.details,
                }
                for event in self.events
            ],
        }

    def _build_frontend(self) -> Path:
        web_root = self.tool_root / "web"
        if not (web_root / "node_modules").is_dir():
            raise RunFailure(
                f"Frontend dependencies are missing. Run `npm ci` in {web_root}` first."
            )
        result = subprocess.run(
            ["npm", "run", "build"], cwd=web_root, text=True, capture_output=True
        )
        if result.returncode:
            raise RunFailure(f"Frontend build failed:\n{result.stderr.strip()}")
        static_root = web_root / "dist"
        if not (static_root / "index.html").is_file():
            raise RunFailure("Frontend build did not create web/dist/index.html")
        return static_root

    def _begin_gateway_observation(self) -> None:
        if not self.config.require_gateway_events:
            return
        if not self.config.gateway_events_url:
            raise RunFailure("Gateway event assertions require a gateway events URL")
        if self._gateway_events is None:
            self._gateway_events = GatewayEventObserver(
                self.config.gateway_events_url
            )
        try:
            self._gateway_events.begin()
        except GatewayEventError as error:
            raise RunFailure(str(error), list(self.events)) from error

    def _wait_for_prompt_end(
        self,
        server: LocalRunServer,
        page: Any,
        call_deadline: float,
        audio_index: int = 0,
    ) -> None:
        gate = PromptGate(
            self.config.remote_silence_seconds,
            self.config.remote_prompt_occurrence,
        )
        deadline = min(
            time.monotonic() + self.config.prompt_timeout_seconds, call_deadline
        )
        fallback_deadline = (
            time.monotonic() + self.config.initial_silence_fallback_seconds
            if self.config.initial_silence_fallback_seconds > 0
            else None
        )
        while time.monotonic() < deadline:
            event = self._next_event(server, min(0.2, deadline - time.monotonic()))
            if event:
                if event.name == "remote_audio_active":
                    gate.remote_audio_active()
                elif event.name == "remote_audio_inactive":
                    gate.remote_audio_inactive(time.monotonic())
            if gate.ready_to_inject(time.monotonic()):
                self._command(
                    page,
                    "injectAudio",
                    {"index": audio_index, "trigger": "remote_prompt"},
                )
                gate.mark_injected()
                return
            if (
                fallback_deadline is not None
                and not gate.remote_activity_observed
                and time.monotonic() >= fallback_deadline
            ):
                self._command(
                    page,
                    "injectAudio",
                    {
                        "index": audio_index,
                        "trigger": "initial_silence_fallback",
                    },
                )
                gate.mark_injected()
                return
        raise RunFailure(
            "No completed remote prompt was detected before the prompt or call timeout"
        )

    def _execute_steps(
        self,
        server: LocalRunServer,
        page: Any,
        call_deadline: float,
    ) -> dict[str, Any]:
        """Execute ordered Playwright-shaped action and expectation steps."""
        step_results: list[dict[str, Any]] = []
        observations: list[ResponseObservation] = []
        last_injection: RunEvent | None = None
        first_action = True
        prior_response_active = False
        events_during_injection: tuple[RunEvent, ...] = ()

        for step_index, step in enumerate(self.config.steps):
            if isinstance(step, RunAction):
                audio_index = step.audio_index
                if first_action:
                    self._wait_for_prompt_end(
                        server,
                        page,
                        call_deadline,
                        audio_index,
                    )
                    first_action = False
                else:
                    self._command(
                        page,
                        "injectAudio",
                        {
                            "index": audio_index,
                            "trigger": "scenario_step",
                        },
                    )
                last_injection, events_during_injection = (
                    self._wait_for_injection_finished(
                        server,
                        audio_index,
                        self._bounded_timeout(30, call_deadline),
                    )
                )
                step_results.append(
                    {
                        "index": step_index,
                        "kind": "action",
                        "name": step.name,
                        "audio_index": audio_index,
                        "finished_timestamp": last_injection.timestamp,
                    }
                )
                continue

            if not isinstance(step, RunExpectation):
                raise RunFailure(f"Unsupported scenario step: {step!r}")
            if last_injection is None:
                raise RunFailure("Expectation has no preceding caller injection")

            if step.outcome == ExpectedOutcome.RESPONSE_START:
                response_start = self._wait_for_response_start(
                    server,
                    call_deadline,
                    prefetched_events=events_during_injection,
                    ignore_current_prompt=prior_response_active,
                )
                prior_response_active = True
                latency_seconds = max(
                    0.0,
                    response_start.timestamp - last_injection.timestamp,
                )
                self._assert_latency_target(
                    latency_seconds,
                    step.max_latency_seconds,
                )
                step_results.append(
                    {
                        "index": step_index,
                        "kind": "expect",
                        "name": step.name,
                        "outcome": step.outcome.value,
                        "observed_timestamp": response_start.timestamp,
                        "latency_seconds": latency_seconds,
                    }
                )
                continue

            observation = self._wait_for_remote_prompts(
                server,
                call_deadline,
                last_injection,
                wait_for_disconnect=(
                    step.outcome == ExpectedOutcome.SESSION_END
                ),
                expected_response_prompts=step.response_prompts,
                prefetched_events=events_during_injection,
                ignore_current_prompt=prior_response_active,
            )
            prior_response_active = False
            self._assert_latency_target(
                observation.latency_seconds,
                step.max_latency_seconds,
            )
            observations.append(observation)
            step_results.append(
                {
                    "index": step_index,
                    "kind": "expect",
                    "name": step.name,
                    "outcome": step.outcome.value,
                    "observed_response_prompts": observation.prompt_count,
                    "latency_seconds": observation.latency_seconds,
                }
            )
            gateway_terminal_event = self._assert_gateway_outcome(
                step.outcome,
                self._gateway_timeout_seconds(
                    step.outcome,
                    call_deadline,
                    wait_for_normal=step_index == len(self.config.steps) - 1,
                ),
            )
            step_results[-1]["gateway_terminal_event"] = gateway_terminal_event

            if step.outcome == ExpectedOutcome.SESSION_END:
                disconnect = observation.disconnect_event
                if disconnect is None:
                    raise RunFailure(
                        "WxCC did not disconnect after the successful "
                        "task-completion response"
                    )
                return self._scenario_result(
                    "remote_disconnect",
                    observations,
                    disconnect,
                    step_results,
                )
            if step.outcome == ExpectedOutcome.TRANSFER:
                if step.connected_observation_seconds > 0:
                    self._assert_call_remains_connected(
                        server,
                        call_deadline,
                        step.connected_observation_seconds,
                    )

        completion_reason, disconnect = self._end_call_locally(
            server, page, call_deadline
        )
        return self._scenario_result(
            completion_reason,
            observations,
            disconnect,
            step_results,
        )

    @staticmethod
    def _assert_latency_target(
        observed_seconds: float,
        maximum_seconds: float | None,
    ) -> None:
        if maximum_seconds is not None and observed_seconds > maximum_seconds:
            raise RunFailure(
                f"Remote response latency {observed_seconds:.3f}s exceeded "
                f"target {maximum_seconds:.3f}s"
            )

    def _assert_gateway_outcome(
        self,
        expected: ExpectedOutcome,
        timeout_seconds: float,
    ) -> dict[str, Any] | None:
        if self._gateway_events is None:
            return None
        try:
            return self._gateway_events.assert_outcome(expected, timeout_seconds)
        except GatewayEventError as error:
            raise RunFailure(str(error), list(self.events)) from error

    def _gateway_timeout_seconds(
        self,
        expected: ExpectedOutcome,
        call_deadline: float,
        *,
        wait_for_normal: bool,
    ) -> float:
        if expected in {ExpectedOutcome.SESSION_END, ExpectedOutcome.TRANSFER}:
            configured_timeout = self.config.response_timeout_seconds
        elif wait_for_normal:
            configured_timeout = self.config.post_audio_grace_seconds
        else:
            return 0.0
        return min(
            configured_timeout,
            max(0.0, call_deadline - time.monotonic()),
        )

    def _wait_for_response_start(
        self,
        server: LocalRunServer,
        call_deadline: float,
        *,
        prefetched_events: tuple[RunEvent, ...] = (),
        ignore_current_prompt: bool = False,
    ) -> RunEvent:
        deadline = min(
            time.monotonic() + self.config.response_timeout_seconds,
            call_deadline,
        )
        pending = deque(prefetched_events)
        waiting_for_prior_inactive = ignore_current_prompt
        while time.monotonic() < deadline:
            event = (
                pending.popleft()
                if pending
                else self._next_event(
                    server, min(0.2, deadline - time.monotonic())
                )
            )
            if event is None:
                continue
            if waiting_for_prior_inactive:
                if event.name == "remote_audio_inactive":
                    waiting_for_prior_inactive = False
                elif event.name == "disconnect":
                    raise RunFailure(
                        "Call disconnected before remote response audio started"
                    )
                continue
            if event.name == "remote_audio_active":
                return event
            if event.name == "disconnect":
                raise RunFailure(
                    "Call disconnected before remote response audio started"
                )
        raise RunFailure("No remote response audio started after caller injection")

    def _wait_for_injection_finished(
        self,
        server: LocalRunServer,
        audio_index: int,
        timeout: float,
    ) -> tuple[RunEvent, tuple[RunEvent, ...]]:
        """Wait for one caller asset while retaining concurrent remote events."""
        deadline = time.monotonic() + timeout
        concurrent_events: list[RunEvent] = []
        while time.monotonic() < deadline:
            event = self._next_event(
                server, min(0.2, deadline - time.monotonic())
            )
            if event is None:
                continue
            if (
                event.name == "injection_finished"
                and event.details.get("injectionIndex") == audio_index
            ):
                return event, tuple(concurrent_events)
            if event.name in {
                "remote_audio_active",
                "remote_audio_inactive",
                "disconnect",
            }:
                concurrent_events.append(event)
        raise RunFailure(
            f"Timed out after {timeout:.1f}s waiting for caller audio {audio_index}"
        )

    @staticmethod
    def _scenario_result(
        completion_reason: str,
        observations: list[ResponseObservation],
        disconnect: RunEvent | None,
        step_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        gateway_terminal_event = next(
            (
                step["gateway_terminal_event"]
                for step in reversed(step_results)
                if step.get("gateway_terminal_event") is not None
            ),
            None,
        )
        return {
            "completion_reason": completion_reason,
            "remote_response_observed": bool(observations),
            "remote_response_latency_seconds": (
                observations[-1].latency_seconds if observations else None
            ),
            "observed_remote_prompt_count": sum(
                observation.prompt_count for observation in observations
            ),
            "disconnect": disconnect.details if disconnect else None,
            "gateway_terminal_event": gateway_terminal_event,
            "steps": step_results,
        }

    def _wait_for_established(self, server: LocalRunServer, timeout: float) -> RunEvent:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self._next_event(server, min(0.2, deadline - time.monotonic()))
            if event is None:
                continue
            if event.name == "established":
                return event
            if event.name == "disconnect":
                raise RunFailure("Call disconnected before media was established")
        raise RunFailure(
            f"Timed out after {timeout:.1f}s waiting for the call to establish"
        )

    def _finish_call(
        self,
        server: LocalRunServer,
        page: Any,
        call_deadline: float,
        injection_finished: RunEvent,
    ) -> dict[str, Any]:
        expected_outcome = self.config.expected_outcome
        require_response = (
            self.config.require_remote_response or expected_outcome is not None
        )
        observation: ResponseObservation | None = None
        gateway_terminal_event: dict[str, Any] | None = None
        if require_response:
            observation = self._wait_for_remote_prompts(
                server,
                call_deadline,
                injection_finished,
                wait_for_disconnect=expected_outcome == ExpectedOutcome.SESSION_END,
            )
            gateway_terminal_event = self._assert_gateway_outcome(
                expected_outcome or ExpectedOutcome.RESPONSE,
                self._gateway_timeout_seconds(
                    expected_outcome or ExpectedOutcome.RESPONSE,
                    call_deadline,
                    wait_for_normal=True,
                ),
            )
            if expected_outcome == ExpectedOutcome.SESSION_END:
                disconnect = observation.disconnect_event
                if disconnect is None:
                    raise RunFailure(
                        "WxCC did not disconnect after the successful task-completion "
                        "response"
                    )
                return {
                    "completion_reason": "remote_disconnect",
                    "remote_response_observed": True,
                    "remote_response_latency_seconds": observation.latency_seconds,
                    "observed_remote_prompt_count": observation.prompt_count,
                    "disconnect": disconnect.details,
                    "gateway_terminal_event": gateway_terminal_event,
                }
            if expected_outcome == ExpectedOutcome.TRANSFER:
                if self.config.connected_observation_seconds > 0:
                    self._assert_call_remains_connected(
                        server,
                        call_deadline,
                        self.config.connected_observation_seconds,
                    )
        else:
            grace_deadline = min(
                time.monotonic() + self.config.post_audio_grace_seconds,
                call_deadline,
            )
            while time.monotonic() < grace_deadline:
                event = self._next_event(
                    server,
                    min(0.2, grace_deadline - time.monotonic()),
                )
                if event and event.name == "disconnect":
                    return {
                        "completion_reason": "remote_disconnect",
                        "remote_response_observed": False,
                        "remote_response_latency_seconds": None,
                        "observed_remote_prompt_count": 0,
                        "disconnect": event.details,
                        "gateway_terminal_event": None,
                    }
        completion_reason, disconnect = self._end_call_locally(
            server, page, call_deadline
        )
        return {
            "completion_reason": completion_reason,
            "remote_response_observed": observation is not None,
            "remote_response_latency_seconds": (
                observation.latency_seconds if observation else None
            ),
            "observed_remote_prompt_count": (
                observation.prompt_count if observation else 0
            ),
            "disconnect": disconnect.details if disconnect else None,
            "gateway_terminal_event": gateway_terminal_event,
        }

    def _end_call_locally(
        self,
        server: LocalRunServer,
        page: Any,
        call_deadline: float,
    ) -> tuple[str, RunEvent | None]:
        self._command(page, "endCall")
        try:
            disconnect = self._wait_for(
                server,
                lambda event: event.name == "disconnect",
                self._bounded_timeout(15, call_deadline),
            )
            completion_reason = (
                "caller_disconnect"
                if disconnect.details.get("initiatedByCaller", True)
                else "remote_disconnect"
            )
        except RunFailure as error:
            if "Timed out" not in str(error):
                raise
            completion_reason = "caller_end_requested"
            disconnect = None
        return completion_reason, disconnect

    def _wait_for_remote_prompts(
        self,
        server: LocalRunServer,
        call_deadline: float,
        injection_finished: RunEvent,
        *,
        wait_for_disconnect: bool = False,
        expected_response_prompts: int | None = None,
        prefetched_events: tuple[RunEvent, ...] = (),
        ignore_current_prompt: bool = False,
    ) -> ResponseObservation:
        required_prompts = (
            self.config.expected_response_prompts
            if expected_response_prompts is None
            else expected_response_prompts
        )
        deadline = min(
            time.monotonic() + self.config.response_timeout_seconds,
            call_deadline,
        )
        first_active: RunEvent | None = None
        remote_active = False
        quiet_since: float | None = None
        prompt_count = 0
        pending = deque(prefetched_events)
        waiting_for_prior_inactive = ignore_current_prompt
        while time.monotonic() < deadline:
            event = (
                pending.popleft()
                if pending
                else self._next_event(
                    server,
                    min(0.2, deadline - time.monotonic()),
                )
            )
            now = time.monotonic()
            if event is not None:
                if waiting_for_prior_inactive:
                    if event.name == "remote_audio_inactive":
                        waiting_for_prior_inactive = False
                    elif event.name == "disconnect":
                        raise RunFailure(
                            "Call disconnected before the required remote "
                            "response outcome was observed"
                        )
                    continue
                if event.name == "disconnect":
                    if wait_for_disconnect and first_active is not None:
                        if remote_active or quiet_since is not None:
                            prompt_count += 1
                        if prompt_count >= required_prompts:
                            return ResponseObservation(
                                prompt_count=prompt_count,
                                latency_seconds=max(
                                    0.0,
                                    first_active.timestamp
                                    - injection_finished.timestamp,
                                ),
                                disconnect_event=event,
                            )
                    raise RunFailure(
                        "Call disconnected before the required remote response "
                        "outcome was observed"
                    )
                if event.name == "remote_audio_active":
                    if first_active is None:
                        first_active = event
                    remote_active = True
                    quiet_since = None
                elif event.name == "remote_audio_inactive" and first_active:
                    remote_active = False
                    quiet_since = now
            if (
                first_active is not None
                and quiet_since is not None
                and now - quiet_since >= self.config.remote_silence_seconds
            ):
                prompt_count += 1
                quiet_since = None
                if (
                    prompt_count >= required_prompts
                    and not wait_for_disconnect
                ):
                    return ResponseObservation(
                        prompt_count=prompt_count,
                        latency_seconds=max(
                            0.0,
                            first_active.timestamp - injection_finished.timestamp,
                        ),
                    )
        if first_active is None:
            raise RunFailure(
                "No remote response was observed after caller audio finished"
            )
        if wait_for_disconnect:
            raise RunFailure(
                "Required remote disconnect was not observed after the "
                "task-completion response"
            )
        raise RunFailure(
            f"Observed {prompt_count} of "
            f"{required_prompts} required completed remote "
            "response prompt(s)"
        )

    def _assert_call_remains_connected(
        self,
        server: LocalRunServer,
        call_deadline: float,
        observation_seconds: float,
    ) -> None:
        deadline = min(time.monotonic() + observation_seconds, call_deadline)
        while time.monotonic() < deadline:
            event = self._next_event(
                server,
                min(0.2, deadline - time.monotonic()),
            )
            if event and event.name == "disconnect":
                raise RunFailure(
                    "Call disconnected instead of remaining connected for "
                    "WxCC agent routing"
                )
        if time.monotonic() >= call_deadline:
            raise RunFailure(
                "Call timeout expired before the transfer observation completed"
            )

    @staticmethod
    def _bounded_timeout(requested: float, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RunFailure("Call timed out")
        return min(requested, remaining)

    def _command(self, page: Any, command: str, argument: Any = None) -> None:
        try:
            page.evaluate(
                "payload => window.byovaE2E[payload.command](payload.argument)",
                {"command": command, "argument": argument},
            )
        except PlaywrightError as error:
            raise RunFailure(f"Browser command {command!r} failed: {error}") from error

    def _wait_for(
        self, server: LocalRunServer, predicate: Any, timeout: float
    ) -> RunEvent:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            event = self._next_event(server, min(0.2, deadline - time.monotonic()))
            if event and predicate(event):
                return event
        raise RunFailure(f"Timed out after {timeout:.1f}s waiting for browser event")

    def _next_event(self, server: LocalRunServer, timeout: float) -> RunEvent | None:
        event = server.next_event(max(timeout, 0.01))
        if event is None:
            return None
        self.events.append(event)
        if event.name == "error":
            raise RunFailure(str(event.details.get("message", "Browser client failed")))
        return event

    def _record_console(self, source: str, message: str) -> None:
        if source in {"error", "warning", "pageerror"}:
            self.browser_diagnostics.append(f"{source}: {message}")

    def _record_failed_response(self, response: Any) -> None:
        parsed = urlsplit(response.url)
        is_mobius_device_request = (
            parsed.netloc.endswith("wbx2.com")
            and "/api/v1/calling/web/" in parsed.path
            and "/device" in parsed.path
        )
        if response.status < 400 and not is_mobius_device_request:
            return
        self.browser_diagnostics.append(
            f"http {response.status} {response.request.method}: "
            f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        )
