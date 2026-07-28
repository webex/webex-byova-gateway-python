import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pytest
from byova_e2e.models import ExpectedOutcome, RunConfig, RunEvent
from byova_e2e.runner import BrowserRunner, RunFailure
from playwright.sync_api import Error as PlaywrightError


class _Server:
    def __init__(self, *_args) -> None:
        self.url = "http://127.0.0.1:9999/"
        self.closed = False

    def start(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _Page:
    def on(self, *_args) -> None:
        pass

    def goto(self, *_args, **_kwargs) -> None:
        raise PlaywrightError("navigation lost")


class _Context:
    def new_page(self) -> _Page:
        return _Page()

    def close(self) -> None:
        raise PlaywrightError("context already closed")


class _Browser:
    def new_context(self, **_kwargs) -> _Context:
        return _Context()

    def close(self) -> None:
        raise PlaywrightError("browser already closed")


class _Chromium:
    def launch(self, **_kwargs) -> _Browser:
        return _Browser()


class _Playwright:
    chromium = _Chromium()


@contextmanager
def _sync_playwright():
    yield _Playwright()


def _config(tmp_path: Path) -> RunConfig:
    return RunConfig(
        destination="9999",
        access_token="test-token",
        audio_path=tmp_path / "caller.wav",
        audio_sha256="0" * 64,
        audio_duration_seconds=1,
        remote_silence_seconds=0.75,
        initial_silence_fallback_seconds=10,
        prompt_timeout_seconds=60,
        call_timeout_seconds=120,
        post_audio_grace_seconds=5,
    )


def test_browser_failure_is_reported_without_masking_cleanup_error(
    tmp_path, monkeypatch
) -> None:
    server = _Server()
    monkeypatch.setattr("byova_e2e.runner.LocalRunServer", lambda *_args: server)
    monkeypatch.setattr("byova_e2e.runner.sync_playwright", _sync_playwright)
    runner = BrowserRunner(tmp_path, _config(tmp_path))
    monkeypatch.setattr(runner, "_build_frontend", lambda: tmp_path)

    with pytest.raises(RunFailure, match="Browser automation failed: navigation lost"):
        runner.run()

    assert server.closed


class _EventServer:
    def __init__(self, events: list[RunEvent]) -> None:
        self.events = list(events)

    def next_event(self, _timeout: float) -> RunEvent | None:
        return self.events.pop(0) if self.events else None


def test_required_remote_response_records_latency_and_waits_for_quiet(
    tmp_path,
) -> None:
    config = replace(
        _config(tmp_path),
        require_remote_response=True,
        response_timeout_seconds=1,
        remote_silence_seconds=0,
    )
    runner = BrowserRunner(tmp_path, config)
    server = _EventServer(
        [
            RunEvent("remote_audio_active", 12.5),
            RunEvent("remote_audio_inactive", 14.0),
        ]
    )

    observation = runner._wait_for_remote_prompts(
        server,
        time.monotonic() + 1,
        RunEvent("injection_finished", 10.0),
    )

    assert observation.latency_seconds == 2.5
    assert observation.prompt_count == 1
    assert observation.disconnect_event is None
    assert [event.name for event in runner.events] == [
        "remote_audio_active",
        "remote_audio_inactive",
    ]


def test_transfer_requires_two_completed_announcements(tmp_path) -> None:
    config = replace(
        _config(tmp_path),
        expected_outcome=ExpectedOutcome.TRANSFER,
        expected_response_prompts=2,
        response_timeout_seconds=1,
        remote_silence_seconds=0,
    )
    runner = BrowserRunner(tmp_path, config)
    server = _EventServer(
        [
            RunEvent("remote_audio_active", 12.5),
            RunEvent("remote_audio_inactive", 13.0),
            RunEvent("remote_audio_active", 14.0),
            RunEvent("remote_audio_inactive", 15.0),
        ]
    )

    observation = runner._wait_for_remote_prompts(
        server,
        time.monotonic() + 1,
        RunEvent("injection_finished", 10.0),
    )

    assert observation.prompt_count == 2
    assert observation.latency_seconds == 2.5


def test_session_end_requires_remote_response_then_disconnect(tmp_path) -> None:
    config = replace(
        _config(tmp_path),
        expected_outcome=ExpectedOutcome.SESSION_END,
        expected_response_prompts=1,
        response_timeout_seconds=1,
        remote_silence_seconds=0.75,
    )
    runner = BrowserRunner(tmp_path, config)
    disconnect = RunEvent(
        "disconnect",
        15.0,
        {
            "code": 0,
            "cause": "Normal Disconnect.",
            "initiatedByCaller": False,
        },
    )
    server = _EventServer(
        [
            RunEvent("remote_audio_active", 12.5),
            RunEvent("remote_audio_inactive", 14.0),
            disconnect,
        ]
    )

    observation = runner._wait_for_remote_prompts(
        server,
        time.monotonic() + 1,
        RunEvent("injection_finished", 10.0),
        wait_for_disconnect=True,
    )

    assert observation.prompt_count == 1
    assert observation.disconnect_event is disconnect
    assert observation.latency_seconds == 2.5


def test_session_end_rejects_disconnect_without_completion_announcement(
    tmp_path,
) -> None:
    config = replace(
        _config(tmp_path),
        expected_outcome=ExpectedOutcome.SESSION_END,
        response_timeout_seconds=0.1,
    )
    runner = BrowserRunner(tmp_path, config)
    server = _EventServer([RunEvent("disconnect", 12.0)])

    with pytest.raises(
        RunFailure,
        match="before the required remote response outcome",
    ):
        runner._wait_for_remote_prompts(
            server,
            time.monotonic() + 0.1,
            RunEvent("injection_finished", 10.0),
            wait_for_disconnect=True,
        )


def test_transfer_rejects_disconnect_during_connected_observation(tmp_path) -> None:
    runner = BrowserRunner(tmp_path, _config(tmp_path))
    server = _EventServer([RunEvent("disconnect", 12.0)])

    with pytest.raises(
        RunFailure,
        match="instead of remaining connected",
    ):
        runner._assert_call_remains_connected(
            server,
            time.monotonic() + 1,
            1,
        )
