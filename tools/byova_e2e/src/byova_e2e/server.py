"""Local-only asset/config server and browser event queue."""

from __future__ import annotations

import json
import queue
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .models import RunConfig, RunEvent


class LocalRunServer:
    """Serve the compiled client, prepared WAVs, and an event endpoint."""

    def __init__(self, static_root: Path, config: RunConfig) -> None:
        self._static_root = static_root
        self._config = config
        self._events: queue.Queue[RunEvent] = queue.Queue()
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_type())
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address
        return f"http://{host}:{port}/"

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def next_event(self, timeout: float) -> RunEvent | None:
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return None

    def _handler_type(self) -> type[SimpleHTTPRequestHandler]:
        static_root = self._static_root
        config = self._config
        audio_assets = config.prepared_audio()
        events = self._events

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, directory=str(static_root), **kwargs)

            def log_message(self, _format: str, *_args: Any) -> None:
                """Never log the config response, which contains an access token."""

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/api/config":
                    payload = {
                        "accessToken": config.access_token,
                        "destination": config.destination,
                        "audioUrl": "/run/caller.wav",
                        "audioUrls": [
                            f"/run/caller-{index}.wav"
                            for index in range(len(audio_assets))
                        ],
                    }
                    self._write_json(payload)
                    return
                if self.path == "/run/caller.wav":
                    self._send_audio(audio_assets[0].path)
                    return
                if self.path.startswith("/run/caller-") and self.path.endswith(
                    ".wav"
                ):
                    index_text = self.path.removeprefix(
                        "/run/caller-"
                    ).removesuffix(".wav")
                    try:
                        index = int(index_text)
                        if index < 0:
                            raise IndexError
                        audio_asset = audio_assets[index]
                    except (ValueError, IndexError):
                        self.send_error(HTTPStatus.NOT_FOUND)
                        return
                    self._send_audio(audio_asset.path)
                    return
                super().do_GET()

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/api/events":
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                try:
                    content_length = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(content_length))
                    event = RunEvent(
                        name=str(payload["name"]),
                        timestamp=float(payload.get("timestamp", time.monotonic())),
                        details=dict(payload.get("details", {})),
                        received_at_utc=datetime.now(timezone.utc).isoformat(),
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                    self.send_error(HTTPStatus.BAD_REQUEST, str(error))
                    return
                events.put(event)
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()

            def _write_json(self, payload: dict[str, Any]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_audio(self, path: Path) -> None:
                body = path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "audio/wav")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler
