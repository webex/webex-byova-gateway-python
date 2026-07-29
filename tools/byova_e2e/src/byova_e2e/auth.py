"""Local OAuth authorization and refresh-token storage for the test caller."""

from __future__ import annotations

import json
import os
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import requests

AUTHORIZE_URL = "https://webexapis.com/v1/authorize"
TOKEN_URL = "https://webexapis.com/v1/access_token"
SCOPES = ("spark:xsi", "spark:calls_write", "spark:calls_read", "spark:webrtc_calling")
TOKEN_EXPIRY_SKEW_SECONDS = 60
TOKEN_PATH_ENVIRONMENT_VARIABLE = "BYOVA_E2E_WEBEX_TOKEN_PATH"


class OAuthError(RuntimeError):
    """An OAuth configuration, callback, or token-exchange failure."""


def default_token_path() -> Path:
    """Return a user-level token path shared by repository worktrees."""
    if configured_path := os.environ.get(TOKEN_PATH_ENVIRONMENT_VARIABLE):
        token_path = Path(configured_path).expanduser()
        if not token_path.is_absolute():
            raise OAuthError(
                f"${TOKEN_PATH_ENVIRONMENT_VARIABLE} must be an absolute path"
            )
        return token_path
    state_root = Path(
        os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")
    ).expanduser()
    return state_root / "byova-e2e" / "oauth-token.json"


def load_local_environment(path: Path) -> None:
    """Load a minimal local `.env` file without overriding the operator's shell."""
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise OAuthError(
            f"Cannot read local environment file {path}: {error}"
        ) from error

    for number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        if "=" not in line:
            raise OAuthError(f"Invalid local environment entry at {path}:{number}")
        name, value = line.split("=", maxsplit=1)
        name = name.strip()
        value = value.strip()
        if not name.startswith("BYOVA_E2E_"):
            raise OAuthError(
                f"Only BYOVA_E2E_* variables are allowed in {path}:{number}"
            )
        if value[:1] in {'"', "'"} and value[-1:] == value[:1]:
            value = value[1:-1]
        os.environ.setdefault(name, value)


@dataclass(frozen=True)
class OAuthCredentials:
    """Client credentials kept only in the operator's environment."""

    client_id: str
    client_secret: str
    redirect_uri: str

    @classmethod
    def from_environment(cls) -> OAuthCredentials:
        missing = [
            name
            for name in ("BYOVA_E2E_WEBEX_CLIENT_ID", "BYOVA_E2E_WEBEX_CLIENT_SECRET")
            if not os.environ.get(name)
        ]
        if missing:
            names = ", ".join(f"${name}" for name in missing)
            raise OAuthError(f"OAuth login requires {names}")
        return cls(
            client_id=os.environ["BYOVA_E2E_WEBEX_CLIENT_ID"],
            client_secret=os.environ["BYOVA_E2E_WEBEX_CLIENT_SECRET"],
            redirect_uri=os.environ.get(
                "BYOVA_E2E_WEBEX_REDIRECT_URI", "http://localhost:8765/oauth/callback"
            ),
        )


class OAuthTokenStore:
    """Persist refreshable OAuth credentials with owner-only file permissions."""

    def __init__(self, path: Path, legacy_path: Path | None = None) -> None:
        self.path = path
        self.legacy_path = legacy_path

    def load(self) -> dict[str, Any] | None:
        if self.path.is_file():
            return self._load_path(self.path)
        if self.legacy_path is None or not self.legacy_path.is_file():
            return None
        payload = self._load_path(self.legacy_path)
        self.save(payload)
        return payload

    def _load_path(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise OAuthError(
                f"Cannot read saved OAuth token at {path}: {error}"
            ) from error
        if not isinstance(payload, dict) or not isinstance(
            payload.get("access_token"), str
        ):
            raise OAuthError(f"Saved OAuth token at {path} is invalid")
        return payload

    def save(self, token: dict[str, Any]) -> None:
        parent_exists = self.path.parent.exists()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not parent_exists:
            self.path.parent.chmod(0o700)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(json.dumps(token, indent=2, sort_keys=True) + "\n")
            temporary_path.chmod(0o600)
            temporary_path.replace(self.path)
            self.path.chmod(0o600)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)


def authorization_url(
    credentials: OAuthCredentials,
    state: str,
    login_hint: str | None = None,
) -> str:
    """Return the exact consent URL for the configured local callback."""
    parameters = {
        "client_id": credentials.client_id,
        "response_type": "code",
        "redirect_uri": credentials.redirect_uri,
        "scope": " ".join(SCOPES),
        "state": state,
    }
    if login_hint:
        parameters["prompt"] = "select_account"
        parameters["login_hint"] = login_hint
    return f"{AUTHORIZE_URL}?{urlencode(parameters)}"


def exchange_code(credentials: OAuthCredentials, code: str) -> dict[str, Any]:
    """Exchange an authorization code and annotate the local expiry time."""
    return _request_token(
        {
            "grant_type": "authorization_code",
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "redirect_uri": credentials.redirect_uri,
            "code": code,
        }
    )


def refresh_token(credentials: OAuthCredentials, refresh: str) -> dict[str, Any]:
    """Refresh a previously saved token without opening a browser."""
    return _request_token(
        {
            "grant_type": "refresh_token",
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "refresh_token": refresh,
        }
    )


def access_token_for_run(store: OAuthTokenStore) -> str:
    """Get a token override or a saved token, refreshing it when necessary."""
    if override := os.environ.get("BYOVA_E2E_WEBEX_ACCESS_TOKEN"):
        return override
    token = store.load()
    if token is None:
        raise OAuthError(
            "No saved OAuth token. Run `byova-e2e login`, or set $BYOVA_E2E_WEBEX_ACCESS_TOKEN."
        )
    expires_at = float(token.get("expires_at", 0))
    if expires_at > time.time() + TOKEN_EXPIRY_SKEW_SECONDS:
        return str(token["access_token"])
    refresh = token.get("refresh_token")
    if not isinstance(refresh, str) or not refresh:
        raise OAuthError(
            "Saved OAuth token has expired and has no refresh token; run `byova-e2e login`"
        )
    refreshed = refresh_token(OAuthCredentials.from_environment(), refresh)
    saved_token = _merge_refreshed_token(token, refreshed)
    store.save(saved_token)
    return str(saved_token["access_token"])


def complete_login(store: OAuthTokenStore, timeout_seconds: float) -> str:
    """Print a consent URL, receive the callback locally, and save its tokens."""
    credentials = OAuthCredentials.from_environment()
    callback = OAuthCallbackServer(credentials.redirect_uri)
    state = secrets.token_urlsafe(32)
    callback.start()
    try:
        print(
            "Open this URL in the WxCC Admin Chrome profile and sign in as the dedicated Webex Calling test user:\n"
        )
        print(
            authorization_url(
                credentials,
                state,
                os.environ.get("BYOVA_E2E_TEST_USER_EMAIL"),
            )
        )
        code = callback.wait_for_code(state, timeout_seconds)
        token = exchange_code(credentials, code)
        if (
            not isinstance(token.get("refresh_token"), str)
            or not token["refresh_token"]
        ):
            raise OAuthError(
                "Webex OAuth response did not contain a refresh token; "
                "the authorization was not saved"
            )
        store.save(token)
        return str(store.path)
    finally:
        callback.close()


def _request_token(payload: dict[str, str]) -> dict[str, Any]:
    try:
        response = requests.post(TOKEN_URL, data=payload, timeout=20)
        response.raise_for_status()
        token = response.json()
    except (requests.RequestException, ValueError) as error:
        raise OAuthError(f"Webex OAuth token request failed: {error}") from error
    if not isinstance(token, dict) or not isinstance(token.get("access_token"), str):
        raise OAuthError("Webex OAuth response did not contain an access token")
    received_at = time.time()
    token["expires_at"] = received_at + float(token.get("expires_in", 0))
    return token


def _merge_refreshed_token(
    previous: dict[str, Any], refreshed: dict[str, Any]
) -> dict[str, Any]:
    """Keep a usable refresh token while preferring any rotated token response."""
    merged = {**previous, **refreshed}
    if (
        not isinstance(refreshed.get("refresh_token"), str)
        or not refreshed["refresh_token"]
    ):
        merged["refresh_token"] = previous["refresh_token"]
    return merged


class OAuthCallbackServer:
    """One-use localhost callback listener that rejects unexpected requests."""

    def __init__(self, redirect_uri: str) -> None:
        parsed = urlparse(redirect_uri)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise OAuthError("OAuth redirect URI must be an http localhost callback")
        if not parsed.port or parsed.path != "/oauth/callback":
            raise OAuthError(
                "OAuth redirect URI must use /oauth/callback and an explicit port"
            )
        self._expected_path = parsed.path
        self._result: dict[str, str] = {}
        self._received = threading.Event()
        self._httpd = ThreadingHTTPServer(
            (parsed.hostname, parsed.port), self._handler_type()
        )
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)

    def wait_for_code(self, expected_state: str, timeout_seconds: float) -> str:
        if not self._received.wait(timeout_seconds):
            raise OAuthError("Timed out waiting for the OAuth callback")
        if self._result.get("state") != expected_state:
            raise OAuthError(
                "OAuth callback state did not match the authorization request"
            )
        if error := self._result.get("error"):
            raise OAuthError(f"Webex OAuth authorization failed: {error}")
        if code := self._result.get("code"):
            return code
        raise OAuthError("OAuth callback did not contain an authorization code")

    def _handler_type(self) -> type[BaseHTTPRequestHandler]:
        expected_path = self._expected_path
        result = self._result
        received = self._received

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path != expected_path:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                query = parse_qs(parsed.query)
                for key in ("code", "state", "error"):
                    values = query.get(key)
                    if values:
                        result[key] = values[0]
                received.set()
                body = b"Authorization received. You can close this browser tab."
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: Any) -> None:
                """Do not log callback query parameters."""

        return Handler
