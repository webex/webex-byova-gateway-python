import json
from dataclasses import replace
from pathlib import Path
from urllib.request import Request, urlopen

from byova_e2e.models import AudioAsset, RunConfig
from byova_e2e.server import LocalRunServer


def _config(tmp_path: Path) -> RunConfig:
    audio_path = tmp_path / "caller.wav"
    audio_path.write_bytes(b"RIFF")
    return RunConfig(
        destination="9999",
        access_token="test-token",
        audio_path=audio_path,
        audio_sha256="0" * 64,
        audio_duration_seconds=1,
        remote_silence_seconds=0.75,
        initial_silence_fallback_seconds=10,
        prompt_timeout_seconds=60,
        call_timeout_seconds=120,
        post_audio_grace_seconds=5,
    )


def test_browser_event_receives_utc_correlation_timestamp(tmp_path) -> None:
    static_root = tmp_path / "static"
    static_root.mkdir()
    server = LocalRunServer(static_root, _config(tmp_path))
    server.start()
    try:
        request = Request(
            f"{server.url}api/events",
            data=json.dumps(
                {
                    "name": "injection_finished",
                    "timestamp": 12.5,
                    "details": {},
                }
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            assert response.status == 204

        event = server.next_event(1)
    finally:
        server.close()

    assert event is not None
    assert event.name == "injection_finished"
    assert event.timestamp == 12.5
    assert event.received_at_utc is not None
    assert event.received_at_utc.endswith("+00:00")


def test_server_exposes_each_prepared_audio_asset(tmp_path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    config = replace(
        _config(tmp_path),
        audio_assets=(
            AudioAsset(first, "1" * 64, 1),
            AudioAsset(second, "2" * 64, 1),
        ),
    )
    static_root = tmp_path / "static"
    static_root.mkdir()
    server = LocalRunServer(static_root, config)
    server.start()
    try:
        with urlopen(f"{server.url}api/config") as response:
            browser_config = json.load(response)
        with urlopen(f"{server.url}run/caller.wav") as response:
            legacy_audio = response.read()
        with urlopen(f"{server.url}run/caller-1.wav") as response:
            second_audio = response.read()
    finally:
        server.close()

    assert browser_config["audioUrls"] == [
        "/run/caller-0.wav",
        "/run/caller-1.wav",
    ]
    assert browser_config["audioUrl"] == "/run/caller.wav"
    assert legacy_audio == b"first"
    assert second_audio == b"second"
