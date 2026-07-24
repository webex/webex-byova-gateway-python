"""Python-owned browser lifecycle and prompt-timed call orchestration."""

from __future__ import annotations

from contextlib import suppress
import subprocess
import time
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
                        args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
                    )
                    context = browser.new_context(permissions=["microphone"])
                    page = context.new_page()
                    page.on("console", lambda message: self._record_console(message.type, message.text))
                    page.on("pageerror", lambda error: self._record_console("pageerror", str(error)))
                    page.on("response", self._record_failed_response)
                    page.goto(server.url, wait_until="networkidle")
                    page.click("#start-calling-test")
                    self._wait_for(server, lambda event: event.name == "frontend_ready", 20)
                    self._command(page, "dial")
                    deadline = time.monotonic() + self.config.call_timeout_seconds
                    self._wait_for_established(
                        server,
                        self._bounded_timeout(self.config.prompt_timeout_seconds, deadline),
                    )
                    self._wait_for_prompt_end(server, page, deadline)
                    self._wait_for(server, lambda event: event.name == "injection_finished", self._bounded_timeout(30, deadline))
                    final_reason = self._finish_call(server, page, deadline)
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
            raise RunFailure(f"Browser automation failed: {error}", list(self.events)) from error
        finally:
            server.close()

        return {
            "completion_reason": final_reason,
            "events": [
                {"name": event.name, "timestamp": event.timestamp, "details": event.details}
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

    def _wait_for_prompt_end(self, server: LocalRunServer, page: Any, call_deadline: float) -> None:
        gate = PromptGate(self.config.remote_silence_seconds)
        deadline = min(time.monotonic() + self.config.prompt_timeout_seconds, call_deadline)
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
        raise RunFailure("No completed remote prompt was detected before the prompt or call timeout")

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
        raise RunFailure(f"Timed out after {timeout:.1f}s waiting for the call to establish")

    def _finish_call(self, server: LocalRunServer, page: Any, call_deadline: float) -> str:
        grace_deadline = min(time.monotonic() + self.config.post_audio_grace_seconds, call_deadline)
        while time.monotonic() < grace_deadline:
            event = self._next_event(server, min(0.2, grace_deadline - time.monotonic()))
            if event and event.name == "disconnect":
                return "remote_disconnect"
        self._command(page, "endCall")
        try:
            self._wait_for(
                server,
                lambda event: event.name == "disconnect",
                self._bounded_timeout(15, call_deadline),
            )
            return "caller_disconnect"
        except RunFailure as error:
            if "Timed out" not in str(error):
                raise
            return "caller_end_requested"

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

    def _wait_for(self, server: LocalRunServer, predicate: Any, timeout: float) -> RunEvent:
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
