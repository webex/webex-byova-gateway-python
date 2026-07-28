"""Python-owned browser lifecycle and prompt-timed call orchestration."""

from __future__ import annotations

import subprocess
import time
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from .models import RunConfig, RunEvent
from .server import LocalRunServer
from .state import PromptGate


class RunFailure(RuntimeError):
    """An expected E2E caller failure suitable for a non-zero CLI exit."""

    def __init__(self, message: str, events: list[RunEvent] | None = None) -> None:
        super().__init__(message)
        self.events = events or []


class BrowserRunner:
    """Run one Call SDK browser client while retaining all policy in Python."""

    def __init__(self, tool_root: Path, config: RunConfig) -> None:
        self.tool_root = tool_root
        self.config = config
        self.events: list[RunEvent] = []
        self.browser_diagnostics: list[str] = []

    def run(self) -> dict[str, Any]:
        started_at_utc = datetime.now(timezone.utc).isoformat()
        static_root = self._build_frontend()
        server = LocalRunServer(static_root, self.config)
        server.start()
        final_reason = "unknown"
        try:
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

    def _wait_for_prompt_end(
        self, server: LocalRunServer, page: Any, call_deadline: float
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
                self._command(page, "injectAudio", "remote_prompt")
                gate.mark_injected()
                return
            if (
                fallback_deadline is not None
                and not gate.remote_activity_observed
                and time.monotonic() >= fallback_deadline
            ):
                self._command(page, "injectAudio", "initial_silence_fallback")
                gate.mark_injected()
                return
        raise RunFailure(
            "No completed remote prompt was detected before the prompt or call timeout"
        )

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
        response_latency: float | None = None
        if self.config.require_remote_response:
            response_latency = self._wait_for_remote_response(
                server,
                call_deadline,
                injection_finished,
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
                    }
        self._command(page, "endCall")
        try:
            self._wait_for(
                server,
                lambda event: event.name == "disconnect",
                self._bounded_timeout(15, call_deadline),
            )
            completion_reason = "caller_disconnect"
        except RunFailure as error:
            if "Timed out" not in str(error):
                raise
            completion_reason = "caller_end_requested"
        return {
            "completion_reason": completion_reason,
            "remote_response_observed": response_latency is not None,
            "remote_response_latency_seconds": response_latency,
        }

    def _wait_for_remote_response(
        self,
        server: LocalRunServer,
        call_deadline: float,
        injection_finished: RunEvent,
    ) -> float:
        deadline = min(
            time.monotonic() + self.config.response_timeout_seconds,
            call_deadline,
        )
        first_active: RunEvent | None = None
        quiet_since: float | None = None
        while time.monotonic() < deadline:
            event = self._next_event(
                server,
                min(0.2, deadline - time.monotonic()),
            )
            now = time.monotonic()
            if event is not None:
                if event.name == "disconnect":
                    raise RunFailure(
                        "Call disconnected before the required remote response"
                    )
                if event.name == "remote_audio_active":
                    if first_active is None:
                        first_active = event
                    quiet_since = None
                elif event.name == "remote_audio_inactive" and first_active:
                    quiet_since = now
            if (
                first_active is not None
                and quiet_since is not None
                and now - quiet_since >= self.config.remote_silence_seconds
            ):
                return max(
                    0.0,
                    first_active.timestamp - injection_finished.timestamp,
                )
        if first_active is None:
            raise RunFailure(
                "No remote response was observed after caller audio finished"
            )
        raise RunFailure(
            "Remote response did not become quiet before the response timeout"
        )

    @staticmethod
    def _bounded_timeout(requested: float, deadline: float) -> float:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RunFailure("Call timed out")
        return min(requested, remaining)

    def _command(self, page: Any, command: str, argument: str | None = None) -> None:
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
