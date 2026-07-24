from contextlib import contextmanager
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError

from byova_e2e.models import RunConfig
from byova_e2e.runner import BrowserRunner, RunFailure


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


def test_browser_failure_is_reported_without_masking_cleanup_error(tmp_path, monkeypatch) -> None:
    server = _Server()
    monkeypatch.setattr("byova_e2e.runner.LocalRunServer", lambda *_args: server)
    monkeypatch.setattr("byova_e2e.runner.sync_playwright", _sync_playwright)
    runner = BrowserRunner(tmp_path, _config(tmp_path))
    monkeypatch.setattr(runner, "_build_frontend", lambda: tmp_path)

    with pytest.raises(RunFailure, match="Browser automation failed: navigation lost"):
        runner.run()

    assert server.closed
