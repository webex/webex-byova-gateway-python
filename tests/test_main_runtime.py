"""Tests for process behavior required by ECS/Fargate."""

import logging
import signal
import threading

from main import (
    install_shutdown_signal_handlers,
    restore_signal_handlers,
    setup_logging,
)


def test_stdout_only_logging_does_not_create_configured_files(
    monkeypatch, tmp_path
) -> None:
    gateway_log = tmp_path / "gateway.log"
    web_log = tmp_path / "web.log"
    monkeypatch.setenv("BYOVA_STDOUT_ONLY_LOGGING", "true")

    setup_logging(
        {
            "logging": {
                "gateway": {"level": "INFO", "file": str(gateway_log)},
                "web": {"level": "WARNING", "file": str(web_log)},
            }
        }
    )

    assert not gateway_log.exists()
    assert not web_log.exists()
    assert not any(
        isinstance(handler, logging.FileHandler)
        for handler in logging.getLogger().handlers
    )


def test_shutdown_handler_sets_event_and_can_be_restored(monkeypatch) -> None:
    shutdown_event = threading.Event()
    installed: dict[int, object] = {}
    previous = object()

    monkeypatch.setattr(signal, "getsignal", lambda _signum: previous)
    monkeypatch.setattr(
        signal,
        "signal",
        lambda signum, handler: installed.__setitem__(signum, handler),
    )

    old_handlers = install_shutdown_signal_handlers(shutdown_event)
    installed[signal.SIGTERM](signal.SIGTERM, None)

    assert shutdown_event.is_set()
    assert old_handlers[signal.SIGTERM] is previous

    restored: dict[int, object] = {}
    monkeypatch.setattr(
        signal,
        "signal",
        lambda signum, handler: restored.__setitem__(signum, handler),
    )
    restore_signal_handlers(old_handlers)

    assert restored[signal.SIGTERM] is previous
    assert restored[signal.SIGINT] is previous
