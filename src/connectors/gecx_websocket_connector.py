"""Native WebSocket provider connector for Google CX Agent Studio.

This module changes only the gateway-to-CES transport. The Webex-facing
transport remains selected independently by the connector router.
"""

from __future__ import annotations

import queue
import re
import threading
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import google.auth
import websocket
from google.auth.credentials import with_scopes_if_required
from google.auth.transport.requests import Request
from google.cloud import ces_v1
from google.protobuf import json_format

from .gecx_connector import (
    GECXConnector,
    GECXStreamingSession,
    GECXTerminalOutcome,
    GECXTerminalReason,
)

_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_CES_WEBSOCKET_HOST = "ces.googleapis.com"
_CES_WEBSOCKET_PATH = (
    "/ws/google.cloud.ces.v1.SessionService/BidiRunSession/locations/{location}"
)
_LOCATION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_LOCAL_TEST_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class GECXWebSocketStreamingSession(GECXStreamingSession):
    """Run one CES BidiRunSession over Google's JSON WebSocket gateway."""

    connector: GECXWebSocketConnector

    @staticmethod
    def _serialize_client_message(message: Any) -> str:
        """Serialize a protobuf-plus request with canonical protobuf JSON names."""
        return json_format.MessageToJson(
            message._pb,
            preserving_proto_field_name=False,
            indent=None,
        )

    def _parse_server_message(self, payload: Any) -> Any:
        """Validate and parse one CES JSON response frame."""
        if isinstance(payload, bytes):
            payload_bytes = payload
            payload = payload.decode("utf-8", errors="strict")
        elif isinstance(payload, str):
            payload_bytes = payload.encode("utf-8")
        else:
            raise ValueError(
                f"Unsupported CES WebSocket frame type: {type(payload).__name__}"
            )

        if len(payload_bytes) > self.connector.websocket_max_response_bytes:
            raise ValueError(
                "CES WebSocket response exceeded the configured frame-size limit"
            )

        response_pb = ces_v1.BidiSessionServerMessage()._pb
        json_format.Parse(
            payload,
            response_pb,
            ignore_unknown_fields=True,
            max_recursion_depth=32,
        )
        return ces_v1.BidiSessionServerMessage(response_pb)

    def _send_requests(
        self,
        connection: websocket.WebSocket,
        sender_errors: queue.Queue[Exception],
    ) -> None:
        """Write the ordered request stream while the owner thread reads replies."""
        try:
            for request in self._request_generator():
                if self._stop_event.is_set():
                    break
                connection.send(
                    self._serialize_client_message(request),
                    opcode=websocket.ABNF.OPCODE_TEXT,
                )
        except Exception as exc:
            if not self.is_terminal:
                sender_errors.put(exc)
                try:
                    connection.close()
                except Exception:
                    self.logger.debug(
                        "gecx_websocket_sender_close_failed conversation_id=%s",
                        self.conversation_id,
                        exc_info=True,
                    )

    def _run_stream(self) -> None:
        connection: websocket.WebSocket | None = None
        sender_thread: threading.Thread | None = None
        sender_errors: queue.Queue[Exception] = queue.Queue(maxsize=1)

        try:
            connection = self.connector.create_websocket_connection()
            connection.settimeout(self.connector.websocket_receive_timeout_seconds)
            sender_thread = threading.Thread(
                target=self._send_requests,
                args=(connection, sender_errors),
                name=f"gecx-websocket-send-{self.conversation_id}",
                daemon=True,
            )
            sender_thread.start()

            while not self._stop_event.is_set():
                try:
                    payload = connection.recv()
                except websocket.WebSocketTimeoutException:
                    try:
                        raise sender_errors.get_nowait()
                    except queue.Empty:
                        continue

                if payload in (None, "", b""):
                    break

                self._handle_server_message(self._parse_server_message(payload))
                if self.is_terminal:
                    break

            try:
                raise sender_errors.get_nowait()
            except queue.Empty:
                pass
        except Exception as exc:
            if self.is_terminal:
                self.logger.debug(
                    "gecx_websocket_closed_after_terminal conversation_id=%s "
                    "session=%s error=%r",
                    self.conversation_id,
                    self.session_path,
                    exc,
                )
            else:
                self.logger.error(
                    "gecx_websocket_stream_error conversation_id=%s session=%s "
                    "error=%r",
                    self.conversation_id,
                    self.session_path,
                    exc,
                    exc_info=True,
                )
                # Preserve detailed diagnostics only in server logs. The
                # connector error may be returned to WxCC by start_conversation.
                self._stream_error = "CES WebSocket stream failed"
                self.terminate(
                    reason=GECXTerminalReason.STREAM_ERROR,
                    outcome=GECXTerminalOutcome.SESSION_END,
                    source="websocket_bidi_run_session_exception",
                    metadata={"error": self._stream_error},
                )
        finally:
            if not self.is_terminal:
                self._stream_error = (
                    "CES WebSocket response stream closed without EndSession"
                )
                self.terminate(
                    reason=GECXTerminalReason.STREAM_ERROR,
                    outcome=GECXTerminalOutcome.SESSION_END,
                    source="websocket_bidi_run_session_closed",
                    metadata={"error": self._stream_error},
                )
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    self.logger.debug(
                        "gecx_websocket_close_failed conversation_id=%s",
                        self.conversation_id,
                        exc_info=True,
                    )
            if (
                sender_thread is not None
                and sender_thread.is_alive()
                and sender_thread is not threading.current_thread()
            ):
                sender_thread.join(
                    timeout=self.connector.websocket_sender_join_timeout_seconds
                )
                if sender_thread.is_alive():
                    self.logger.error(
                        "gecx_websocket_sender_join_timeout conversation_id=%s",
                        self.conversation_id,
                    )
            self._stream_started.set()
            self._turn_completed.set()


class GECXWebSocketConnector(GECXConnector):
    """Connect the shared GECX behavior to CES through native WebSockets."""

    def _initialize_provider_transport(
        self,
        credentials: Any | None,
        client_options: Any | None,
    ) -> None:
        del client_options

        scopes = [_CLOUD_PLATFORM_SCOPE]
        if credentials is None:
            credentials, _ = google.auth.default(
                scopes=scopes,
                quota_project_id=self.project_id,
            )
        else:
            credentials = with_scopes_if_required(credentials, scopes)

        self._websocket_credentials = credentials
        self._websocket_credentials_lock = threading.Lock()
        self._websocket_auth_request = Request()

        self.websocket_connect_timeout_seconds = min(
            60.0,
            max(1.0, float(self.config.get("websocket_connect_timeout_seconds", 15))),
        )
        self.websocket_receive_timeout_seconds = min(
            5.0,
            max(0.1, float(self.config.get("websocket_receive_timeout_seconds", 1))),
        )
        self.websocket_sender_join_timeout_seconds = min(
            10.0,
            max(
                0.1,
                float(self.config.get("websocket_sender_join_timeout_seconds", 5)),
            ),
        )
        self.websocket_max_response_bytes = min(
            16 * 1024 * 1024,
            max(
                64 * 1024,
                int(self.config.get("websocket_max_response_bytes", 4 * 1024 * 1024)),
            ),
        )
        self.websocket_url = self._validate_websocket_endpoint(
            self.config.get("websocket_endpoint")
        )

    def _validate_websocket_endpoint(self, configured_endpoint: Any) -> str:
        """Return an allow-listed CES WSS URL and reject SSRF-prone values."""
        location = str(self.location).lower()
        if not _LOCATION_PATTERN.fullmatch(location):
            raise ValueError("GECX WebSocket location has an invalid format")

        expected_path = _CES_WEBSOCKET_PATH.format(location=location)
        endpoint = str(configured_endpoint or "").strip()
        if not endpoint:
            endpoint = f"wss://{_CES_WEBSOCKET_HOST}{expected_path}"

        parsed = urlsplit(endpoint)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError(
                "GECX WebSocket endpoint must not contain credentials, query, or fragment"
            )
        if parsed.path != expected_path:
            raise ValueError(
                "GECX WebSocket endpoint path must match the configured location"
            )

        hostname = (parsed.hostname or "").lower()
        if hostname == _CES_WEBSOCKET_HOST:
            if parsed.scheme != "wss" or parsed.port not in (None, 443):
                raise ValueError(
                    "The public GECX WebSocket endpoint requires wss on port 443"
                )
        elif hostname in _LOCAL_TEST_HOSTS:
            if not bool(self.config.get("allow_insecure_local_websocket", False)):
                raise ValueError(
                    "Local GECX WebSocket endpoints require "
                    "allow_insecure_local_websocket"
                )
            if parsed.scheme not in {"ws", "wss"}:
                raise ValueError("Local GECX WebSocket endpoints require ws or wss")
        else:
            raise ValueError(
                "GECX WebSocket endpoint host is not in the connector allow-list"
            )
        return endpoint

    def _access_token(self, *, force_refresh: bool = False) -> str:
        """Return a current OAuth token without exposing it through logs."""
        with self._websocket_credentials_lock:
            credentials = self._websocket_credentials
            if force_refresh or not credentials.valid or not credentials.token:
                credentials.refresh(self._websocket_auth_request)
            if not credentials.token:
                raise RuntimeError("Google credentials did not provide an access token")
            return str(credentials.token)

    def create_websocket_connection(self) -> websocket.WebSocket:
        """Open one authenticated CES socket, refreshing once after a 401."""
        for attempt in range(2):
            token = self._access_token(force_refresh=attempt > 0)
            try:
                return websocket.create_connection(
                    self.websocket_url,
                    timeout=self.websocket_connect_timeout_seconds,
                    header={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    enable_multithread=True,
                    redirect_limit=0,
                )
            except websocket.WebSocketBadStatusException as exc:
                if exc.status_code == 401 and attempt == 0:
                    self.logger.warning(
                        "GECX WebSocket authentication was rejected; refreshing "
                        "credentials once"
                    )
                    continue
                raise
        raise RuntimeError("Unable to authenticate the GECX WebSocket connection")

    def _create_streaming_session(
        self,
        *,
        conversation_id: str,
        session_path: str,
        async_response_sink: Callable[[dict[str, Any]], bool] | None,
        input_acknowledgement_sink: Callable[[str], None] | None,
    ) -> GECXWebSocketStreamingSession:
        return GECXWebSocketStreamingSession(
            connector=self,
            conversation_id=conversation_id,
            session_path=session_path,
            deployment_path=self.deployment_path,
            initial_message=self.initial_message,
            async_response_sink=async_response_sink,
            input_acknowledgement_sink=input_acknowledgement_sink,
        )

    def get_provider_transport(self) -> str:
        return "websocket"


__all__ = ["GECXWebSocketConnector", "GECXWebSocketStreamingSession"]
