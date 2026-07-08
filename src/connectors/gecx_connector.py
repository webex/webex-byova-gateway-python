"""
Google CX Agent Studio (GECX / CES) Connector implementation.

Bridges Webex BYOVA to Gemini Enterprise for Customer Experience via the
CES BidiRunSession API for real-time bidirectional audio streaming.
"""

from __future__ import annotations

import base64
import logging
import os
import queue
import re
import struct
import threading
import uuid
from typing import Any, Dict, Generator, Iterator, Optional, Tuple

try:
    import audioop

    AUDIOOP_AVAILABLE = True
except ImportError:
    AUDIOOP_AVAILABLE = False
    audioop = None

try:
    from google.api_core import client_options as client_options_lib
    from google.api_core import exceptions as google_exceptions
    from google.auth.transport.requests import Request
    from google.cloud import ces_v1
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials as OAuth2Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    import pickle

    CES_AVAILABLE = True
except ImportError:
    CES_AVAILABLE = False
    ces_v1 = None
    google_exceptions = None
    service_account = None
    OAuth2Credentials = None
    InstalledAppFlow = None
    Request = None
    client_options_lib = None

from .i_vendor_connector import EventTypes, IVendorConnector

# CES session IDs: [a-zA-Z0-9][a-zA-Z0-9-_]{4,62}
_SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-_]{4,62}$")

# Sentinel objects for the inbound control queue
_AUDIO_END = object()
_STREAM_STOP = object()


def _make_ces_session_id() -> str:
    """Return a CES-valid session id."""
    session_id = str(uuid.uuid4()).replace("-", "")
    if not _SESSION_ID_PATTERN.match(session_id):
        session_id = f"s{session_id}"[:63]
    return session_id


def _ces_audio_encoding(name: str) -> int:
    """Map config encoding string to ces_v1.AudioEncoding."""
    normalized = name.upper().replace("AUDIO_ENCODING_", "").replace("-", "_")
    mapping = {
        "LINEAR16": ces_v1.AudioEncoding.LINEAR16,
        "LINEAR_16": ces_v1.AudioEncoding.LINEAR16,
        "MULAW": ces_v1.AudioEncoding.MULAW,
        "ALAW": ces_v1.AudioEncoding.ALAW,
    }
    return mapping.get(normalized, ces_v1.AudioEncoding.MULAW)


class GECXStreamingSession:
    """Manages one CES BidiRunSession for a WxCC conversation."""

    def __init__(
        self,
        connector: "GECXConnector",
        conversation_id: str,
        session_path: str,
        deployment_path: str,
        initial_message: Optional[str] = None,
    ) -> None:
        self.connector = connector
        self.conversation_id = conversation_id
        self.session_path = session_path
        self.deployment_path = deployment_path
        self.initial_message = initial_message
        self.logger = logging.getLogger(__name__)

        self.inbound_queue: queue.Queue = queue.Queue()
        self.outbound_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._stream_started = threading.Event()
        self._stream_error: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        # CES streams TTS output as many small frames per agent turn. WxCC
        # expects one complete, self-describing audio clip per prompt, so we
        # accumulate the raw frames here and emit a single WAV-wrapped clip when
        # the turn completes.
        self._audio_buffer = bytearray()

    def start(self) -> None:
        """Start the background bidi stream thread."""
        self._thread = threading.Thread(
            target=self._run_stream,
            name=f"gecx-bidi-{self.conversation_id}",
            daemon=True,
        )
        self._thread.start()
        if not self._stream_started.wait(timeout=30):
            raise TimeoutError("GECX BidiRunSession did not start within 30 seconds")
        if self._stream_error:
            raise RuntimeError(self._stream_error)

    def stop(self) -> None:
        """Signal the stream to stop and wait for the thread."""
        self._stop_event.set()
        self.inbound_queue.put(_STREAM_STOP)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

    def enqueue_audio(self, audio_chunk: bytes) -> None:
        """Queue an audio chunk for the CES stream."""
        if audio_chunk:
            self.inbound_queue.put(audio_chunk)

    def enqueue_text(self, text: str) -> None:
        """Queue a text turn for the CES stream."""
        if text:
            self.inbound_queue.put(("text", text))

    def enqueue_event(self, event_name: str) -> None:
        """Queue an event for the CES stream."""
        if event_name:
            self.inbound_queue.put(("event", event_name))

    def drain_responses(self) -> list[Dict[str, Any]]:
        """Non-blocking drain of outbound connector responses."""
        responses: list[Dict[str, Any]] = []
        while True:
            try:
                responses.append(self.outbound_queue.get_nowait())
            except queue.Empty:
                break
        return responses

    def wait_for_responses(self, timeout: float = 5.0) -> list[Dict[str, Any]]:
        """Block up to timeout collecting outbound responses."""
        responses: list[Dict[str, Any]] = []
        deadline = timeout
        while deadline > 0:
            try:
                responses.append(self.outbound_queue.get(timeout=min(0.5, deadline)))
            except queue.Empty:
                deadline -= 0.5
                if responses:
                    break
        return responses

    def _request_generator(self) -> Iterator[Any]:
        """Yield BidiSessionClientMessage objects for bidi_run_session."""
        input_audio_config = ces_v1.InputAudioConfig(
            audio_encoding=_ces_audio_encoding(self.connector.input_audio_encoding),
            sample_rate_hertz=self.connector.input_sample_rate_hertz,
        )
        output_audio_config = ces_v1.OutputAudioConfig(
            audio_encoding=_ces_audio_encoding(self.connector.output_audio_encoding),
            sample_rate_hertz=self.connector.output_sample_rate_hertz,
        )
        session_config_kwargs: Dict[str, Any] = {
            "session": self.session_path,
            "input_audio_config": input_audio_config,
            "output_audio_config": output_audio_config,
            "enable_text_streaming": self.connector.enable_partial_responses,
        }
        # deployment/entry_agent are optional; when omitted the session runs
        # against the app's root (draft) agent.
        if self.deployment_path:
            session_config_kwargs["deployment"] = self.deployment_path
        if getattr(self.connector, "entry_agent", None):
            session_config_kwargs["entry_agent"] = self.connector.entry_agent

        session_config = ces_v1.SessionConfig(**session_config_kwargs)

        yield ces_v1.BidiSessionClientMessage(config=session_config)
        self._stream_started.set()

        if self.initial_message:
            yield ces_v1.BidiSessionClientMessage(
                realtime_input=ces_v1.SessionInput(text=self.initial_message)
            )

        while not self._stop_event.is_set():
            try:
                item = self.inbound_queue.get(timeout=0.25)
            except queue.Empty:
                continue

            if item is _STREAM_STOP:
                break
            if item is _AUDIO_END:
                continue
            if isinstance(item, tuple):
                kind, payload = item
                if kind == "text":
                    yield ces_v1.BidiSessionClientMessage(
                        realtime_input=ces_v1.SessionInput(text=payload)
                    )
                elif kind == "event":
                    yield ces_v1.BidiSessionClientMessage(
                        realtime_input=ces_v1.SessionInput(event=payload)
                    )
                continue

            yield ces_v1.BidiSessionClientMessage(
                realtime_input=ces_v1.SessionInput(audio=item)
            )

    def _run_stream(self) -> None:
        try:
            responses = self.connector.session_client.bidi_run_session(
                requests=self._request_generator()
            )
            for server_message in responses:
                if self._stop_event.is_set():
                    break
                self._handle_server_message(server_message)
        except Exception as exc:
            self.logger.error(
                f"[{self.conversation_id}] [GECX] BidiRunSession error: {exc}",
                exc_info=True,
            )
            self._stream_error = str(exc)
            self.outbound_queue.put(
                self.connector.create_error_response(
                    conversation_id=self.conversation_id,
                    error_message=f"GECX stream error: {exc}",
                )
            )
        finally:
            self._stream_started.set()

    def _handle_server_message(self, message: Any) -> None:
        """Map CES server messages to BYOVA connector responses."""
        conversation_id = self.conversation_id

        if message.recognition_result and message.recognition_result.transcript:
            transcript = message.recognition_result.transcript.strip()
            if transcript:
                self.logger.debug(
                    f"[{conversation_id}] [GECX] STT: '{transcript}'"
                )

        if message.interruption_signal:
            self.logger.info(f"[{conversation_id}] [GECX] Barge-in interruption signal")
            with self._lock:
                self._audio_buffer = bytearray()
                while not self.outbound_queue.empty():
                    try:
                        self.outbound_queue.get_nowait()
                    except queue.Empty:
                        break

        if message.session_output:
            output = message.session_output
            response_type = (
                "final" if output.turn_completed else "partial"
            )

            if output.text:
                self.logger.info(
                    f"[{conversation_id}] [GECX] Agent: '{output.text}'"
                )
                self.outbound_queue.put(
                    self.connector.create_response(
                        conversation_id=conversation_id,
                        message_type="agent_response",
                        text=output.text,
                        response_type=response_type,
                    )
                )

            audio_bytes = self._decode_output_audio(output.audio)
            if audio_bytes:
                self.logger.debug(
                    f"[{conversation_id}] [GECX] Buffered audio frame: "
                    f"{len(audio_bytes)} bytes"
                )
                with self._lock:
                    self._audio_buffer.extend(audio_bytes)

            # A completed turn means the full agent utterance has been streamed;
            # emit it to WxCC as a single WAV clip.
            if output.turn_completed:
                self._flush_audio_buffer()

            if output.end_session:
                self._flush_audio_buffer()
                self._emit_session_end(conversation_id, output)
                self._begin_half_close()

        if message.end_session:
            self._flush_audio_buffer()
            self._emit_session_end(conversation_id, message.end_session)
            self._begin_half_close()

        if message.go_away:
            self.logger.warning(f"[{conversation_id}] [GECX] GoAway received, stopping stream")
            self._stop_event.set()

    def _begin_half_close(self) -> None:
        """Half-close the client side of the bidi stream after CES ends a session.

        CES requires the client to stop sending (half-close) within 30s of an
        ``EndSession`` message; otherwise it aborts the RPC with
        ``CLIENT_HALF_CLOSE_TIMEOUT``, which surfaces as a stream error and
        tears the turn down before the transfer/session-end response is
        delivered to WxCC. Signalling the request generator to return
        half-closes the stream cleanly so the RPC completes normally.
        """
        if self._stop_event.is_set():
            return
        self.logger.info(
            f"[{self.conversation_id}] [GECX] EndSession received; half-closing stream"
        )
        self._stop_event.set()
        # Unblock the request generator immediately so it returns (rather than
        # waiting for its queue poll to time out).
        self.inbound_queue.put(_STREAM_STOP)

    def _flush_audio_buffer(self, response_type: str = "final") -> bool:
        """Wrap buffered CES audio in a WxCC WAV clip and enqueue it.

        Returns True if a clip was emitted. Safe to call repeatedly; it is a
        no-op when the buffer is empty.
        """
        with self._lock:
            if not self._audio_buffer:
                return False
            raw_audio = bytes(self._audio_buffer)
            self._audio_buffer = bytearray()

        wav_audio = self.connector.wrap_output_audio(raw_audio)
        if not wav_audio:
            return False

        self.logger.info(
            f"[{self.conversation_id}] [GECX] Audio out: {len(wav_audio)} bytes "
            f"WAV ({len(raw_audio)} raw)"
        )
        self.outbound_queue.put(
            self.connector.create_response(
                conversation_id=self.conversation_id,
                message_type="audio",
                audio_content=wav_audio,
                response_type=response_type,
            )
        )
        return True

    @staticmethod
    def _metadata_to_dict(end_obj: Any) -> Dict[str, Any]:
        """Best-effort conversion of an EndSession.metadata Struct to a dict."""
        raw = getattr(end_obj, "metadata", None)
        if not raw:
            return {}
        # proto-plus Struct fields expose .to_dict() / dict-like access.
        for accessor in ("to_dict",):
            fn = getattr(raw, accessor, None)
            if callable(fn):
                try:
                    return dict(fn())
                except (TypeError, ValueError):
                    pass
        try:
            return dict(raw)
        except (TypeError, ValueError):
            return {}

    def _detect_transfer(self, metadata: Dict[str, Any]) -> Tuple[bool, str]:
        """Decide whether an EndSession represents a human handoff.

        Returns (is_transfer, reason). Detection is driven by the connector's
        configurable ``transfer_metadata_keys`` / ``transfer_reason_keywords``.
        """
        truthy = {"true", "1", "yes", "y", "on"}
        lowered = {str(k).lower(): v for k, v in metadata.items()}

        # 1) Explicit boolean-ish flag keys.
        for key in self.connector.transfer_metadata_keys:
            if key not in lowered:
                continue
            val = lowered[key]
            if isinstance(val, bool) and val:
                return True, str(lowered.get("reason", key))
            if isinstance(val, (int, float)) and not isinstance(val, bool) and val:
                return True, str(lowered.get("reason", key))
            if isinstance(val, str) and val.strip().lower() in truthy:
                return True, str(lowered.get("reason", key))

        # 2) reason/type-style string values containing a transfer keyword.
        for rk in self.connector.transfer_reason_metadata_keys:
            rv = lowered.get(rk)
            if isinstance(rv, str):
                low = rv.lower()
                if any(sub in low for sub in self.connector.transfer_reason_keywords):
                    return True, rv

        # 3) Any truthy metadata whose KEY NAME contains a transfer keyword
        #    (e.g. "session_escalated", "escalated", "agent_handoff"). This
        #    generically catches naming variants the agent may emit.
        for key, val in lowered.items():
            if not any(sub in key for sub in self.connector.transfer_reason_keywords):
                continue
            if isinstance(val, bool) and val:
                return True, key
            if isinstance(val, (int, float)) and not isinstance(val, bool) and val:
                return True, key
            if isinstance(val, str) and val.strip().lower() in truthy:
                return True, key
            if val is None:
                # Bare presence of an escalation-style flag with no value.
                return True, key

        return False, ""

    def _emit_session_end(self, conversation_id: str, end_obj: Any) -> None:
        metadata = self._metadata_to_dict(end_obj)

        # Log the raw metadata so operators can see exactly what the agent sends
        # on escalation and map transfer_metadata_keys accordingly.
        self.logger.info(
            f"[{conversation_id}] [GECX] EndSession metadata: {metadata or '{}'}"
        )

        is_transfer, reason = self._detect_transfer(metadata)
        if is_transfer:
            self.logger.info(
                f"[{conversation_id}] [GECX] Escalation detected -> "
                f"TRANSFER_TO_AGENT (reason: {reason or 'agent_requested_transfer'})"
            )
            self.outbound_queue.put(
                self.connector.create_transfer_response(
                    conversation_id=conversation_id,
                    text="Transferring you to an agent.",
                    reason=reason or "agent_requested_transfer",
                )
            )
            return

        end_event = self.connector.create_output_event(
            EventTypes.SESSION_END,
            "session_ended_by_gecx",
            metadata or None,
        )
        self.outbound_queue.put(
            self.connector.create_response(
                conversation_id=conversation_id,
                message_type="session_end",
                text="",
                response_type="final",
                output_events=[end_event],
            )
        )

    @staticmethod
    def _decode_output_audio(audio_data: Any) -> bytes:
        if not audio_data:
            return b""
        if isinstance(audio_data, bytes):
            return audio_data
        if isinstance(audio_data, str):
            try:
                return base64.b64decode(audio_data)
            except Exception:
                return b""
        return b""


class GECXConnector(IVendorConnector):
    """
    Connector for Google CX Agent Studio (Gemini Enterprise for CX).

    Uses the CES BidiRunSession API for real-time bidirectional voice.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        if not CES_AVAILABLE:
            raise ImportError(
                "google-cloud-ces package not installed. "
                "Install it with: pip install google-cloud-ces"
            )

        self.logger = logging.getLogger(__name__)
        self.config = config

        self.project_id = config.get("project_id")
        self.location = config.get("location", "us")
        self.application_id = config.get("application_id")
        self.deployment_id = config.get("deployment_id")
        self.deployment_path = config.get("deployment")
        # Optional: run against a specific (non-root) agent within the app.
        self.entry_agent = config.get("entry_agent")

        # A deployment is OPTIONAL. When neither a deployment nor an entry_agent
        # is provided, the CES BidiRunSession runs against the app's root agent
        # (the current draft), so an explicitly published deployment is not
        # required. Build the full deployment path only when a deployment id or
        # path was supplied.
        if not self.deployment_path and self.deployment_id:
            if not all([self.project_id, self.location, self.application_id]):
                raise ValueError(
                    "Missing required GECX configuration: deployment_id also "
                    "requires project_id, location, and application_id"
                )
            self.deployment_path = (
                f"projects/{self.project_id}/locations/{self.location}/"
                f"apps/{self.application_id}/deployments/{self.deployment_id}"
            )

        # Backfill project/location/app from a full deployment path if needed.
        if self.deployment_path:
            if not self.application_id:
                match = re.search(r"/apps/([^/]+)", self.deployment_path)
                if match:
                    self.application_id = match.group(1)
            if not self.project_id:
                match = re.search(r"projects/([^/]+)/", self.deployment_path)
                if match:
                    self.project_id = match.group(1)
            if "/locations/" in self.deployment_path:
                match = re.search(r"/locations/([^/]+)/", self.deployment_path)
                if match:
                    self.location = match.group(1)

        # project_id, location, and application_id are always required to build
        # the session path (and therefore reach the app's root agent).
        if not all([self.project_id, self.location, self.application_id]):
            raise ValueError(
                "Missing required GECX configuration: provide project_id, "
                "location, and application_id (deployment is optional and, when "
                "omitted, the app's root/draft agent is used)"
            )

        self.language_code = config.get("language_code", "en-US")
        self.input_sample_rate_hertz = config.get("input_sample_rate_hertz", 8000)
        self.output_sample_rate_hertz = config.get("output_sample_rate_hertz", 8000)
        self.input_audio_encoding = config.get("input_audio_encoding", "MULAW")
        self.output_audio_encoding = config.get("output_audio_encoding", "MULAW")
        self.initial_message = config.get("initial_message", "Hello")
        self.enable_partial_responses = config.get("enable_partial_responses", True)
        self.force_input_format = config.get("force_input_format", "").lower()
        self.agents = config.get("agents", ["GECX Agent"])

        # --- Escalation / human handoff detection ---------------------------
        # CES signals escalation as an EndSession carrying a metadata Struct.
        # The exact keys depend on how the CX Agent Studio agent is configured,
        # so detection is intentionally configurable.
        #
        # 1) If any of these metadata keys is truthy, treat the end as a
        #    transfer-to-human. Values are matched loosely (true/"true"/1/"yes").
        self.transfer_metadata_keys = [
            str(k).lower()
            for k in config.get(
                "transfer_metadata_keys",
                [
                    "transfer",
                    "transfer_to_agent",
                    "transfer_to_human",
                    "escalate",
                    "escalation",
                    "escalated",
                    "session_escalated",
                    "handoff",
                    "human_handoff",
                    "live_agent_handoff",
                ],
            )
        ]
        # 2) If a reason/type-style metadata value contains any of these
        #    substrings, also treat the end as a transfer.
        self.transfer_reason_keywords = [
            str(s).lower()
            for s in config.get(
                "transfer_reason_keywords",
                ["transfer", "escalat", "human", "live agent", "live_agent", "handoff"],
            )
        ]
        # Metadata keys whose (string) values are inspected for the keywords above.
        self.transfer_reason_metadata_keys = [
            str(k).lower()
            for k in config.get(
                "transfer_reason_metadata_keys",
                ["reason", "end_reason", "type", "status", "intent", "action"],
            )
        ]

        self.detected_formats: Dict[str, Tuple[int, str]] = {}
        self.streaming_sessions: Dict[str, GECXStreamingSession] = {}
        self.sessions_lock = threading.Lock()

        credentials = self._load_credentials(config)
        # The streaming SessionService (BidiRunSession) is served from the
        # REGIONAL endpoint (e.g. us-ces.googleapis.com), unlike the global
        # control-plane AgentService on ces.googleapis.com. Default to the
        # regional host for the session client; allow override via config.
        self.api_endpoint = config.get("api_endpoint")
        if not self.api_endpoint:
            if self.location and self.location.lower() != "global":
                # Regional CES runtime endpoint (serves BidiRunSession without
                # needing the x-goog-request-params location header).
                self.api_endpoint = f"ces.{self.location.lower()}.rep.googleapis.com"
        client_option_kwargs: Dict[str, Any] = {}
        if self.project_id:
            client_option_kwargs["quota_project_id"] = self.project_id
        if self.api_endpoint:
            client_option_kwargs["api_endpoint"] = self.api_endpoint
        client_options = (
            client_options_lib.ClientOptions(**client_option_kwargs)
            if client_option_kwargs
            else None
        )

        if credentials:
            self.session_client = ces_v1.SessionServiceClient(
                credentials=credentials,
                client_options=client_options,
            )
        else:
            self.session_client = ces_v1.SessionServiceClient(
                client_options=client_options
            )

        self.app_path = (
            f"projects/{self.project_id}/locations/{self.location}/"
            f"apps/{self.application_id}"
        )
        self.logger.info(
            f"GECXConnector initialized for deployment: {self.deployment_path}"
        )

    def _load_credentials(self, config: Dict[str, Any]) -> Optional[Any]:
        access_token = config.get("access_token")
        service_account_key_path = config.get("service_account_key")
        oauth_client_id = config.get("oauth_client_id")
        oauth_client_secret = config.get("oauth_client_secret")
        oauth_token_file = config.get("oauth_token_file", "gecx_oauth_token.pickle")

        if access_token:
            from google.oauth2.credentials import Credentials

            self.logger.warning(
                "GECX: direct access token in use (~1 hour expiry, no auto-refresh)"
            )
            return Credentials(token=access_token)

        if service_account_key_path and os.path.exists(service_account_key_path):
            self.logger.info(f"GECX: using service account {service_account_key_path}")
            return service_account.Credentials.from_service_account_file(
                service_account_key_path
            )

        if oauth_client_id and oauth_client_secret:
            return self._get_oauth_credentials(
                oauth_client_id, oauth_client_secret, oauth_token_file
            )

        self.logger.info("GECX: using Application Default Credentials")
        return None

    def _get_oauth_credentials(
        self, client_id: str, client_secret: str, token_file: str
    ) -> OAuth2Credentials:
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        creds = None

        if os.path.exists(token_file):
            try:
                with open(token_file, "rb") as token:
                    creds = pickle.load(token)
            except Exception as exc:
                self.logger.warning(f"GECX: failed to load OAuth token: {exc}")

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                client_config = {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost:8090"],
                    }
                }
                flow = InstalledAppFlow.from_client_config(client_config, scopes)
                creds = flow.run_local_server(port=8090, open_browser=True)

            try:
                with open(token_file, "wb") as token:
                    pickle.dump(creds, token)
            except Exception as exc:
                self.logger.warning(f"GECX: failed to save OAuth token: {exc}")

        return creds

    def create_error_response(
        self, conversation_id: str, error_message: str
    ) -> Dict[str, Any]:
        """Build a standardized error response (base class has no such helper)."""
        return self.create_response(
            conversation_id=conversation_id,
            message_type="error",
            text=error_message,
            response_type="final",
            error=error_message,
        )

    @staticmethod
    def _build_wxcc_wav(audio_bytes: bytes, sample_rate: int, encoding: str) -> bytes:
        """Wrap raw audio in a WAV container that WxCC can play.

        WxCC's ``Prompt.audio_content`` carries no encoding metadata, so the
        payload must be a self-describing WAV file. Telephony uses 8 kHz, 8-bit
        mono mu-law; PCM is supported as a fallback.
        """
        if not audio_bytes:
            return b""

        enc = (encoding or "MULAW").upper().replace("AUDIO_ENCODING_", "")
        if enc in ("MULAW", "ULAW", "LINEAR_16_MULAW"):
            audio_format = 7  # WAVE_FORMAT_MULAW
            bits_per_sample = 8
        elif enc == "ALAW":
            audio_format = 6  # WAVE_FORMAT_ALAW
            bits_per_sample = 8
        else:  # LINEAR16 / PCM
            audio_format = 1  # WAVE_FORMAT_PCM
            bits_per_sample = 16

        channels = 1
        bytes_per_sample = bits_per_sample // 8
        block_align = channels * bytes_per_sample
        byte_rate = sample_rate * block_align
        data_size = len(audio_bytes)

        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + data_size,
            b"WAVE",
            b"fmt ",
            16,
            audio_format,
            channels,
            sample_rate,
            byte_rate,
            block_align,
            bits_per_sample,
            b"data",
            data_size,
        )
        return header + audio_bytes

    def wrap_output_audio(self, audio_bytes: bytes) -> bytes:
        """Convert raw CES output audio into a WxCC-playable WAV clip."""
        return self._build_wxcc_wav(
            audio_bytes,
            self.output_sample_rate_hertz,
            self.output_audio_encoding,
        )

    def get_available_agents(self) -> list:
        return self.agents

    def start_conversation(
        self, conversation_id: str, request_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        self.logger.info(f"[GECX] Starting conversation: {conversation_id}")
        try:
            session_id = _make_ces_session_id()
            session_path = f"{self.app_path}/sessions/{session_id}"

            stream_session = GECXStreamingSession(
                connector=self,
                conversation_id=conversation_id,
                session_path=session_path,
                deployment_path=self.deployment_path,
                initial_message=self.initial_message,
            )
            stream_session.start()

            with self.sessions_lock:
                self.streaming_sessions[conversation_id] = stream_session

            welcome_text = "Connected to GECX agent"
            got_text = False
            welcome_audio = b""
            for response in stream_session.wait_for_responses(timeout=8.0):
                if response.get("text") and not got_text:
                    welcome_text = response["text"]
                    got_text = True
                # Each audio response is already a complete WAV clip for one
                # turn; keep the latest non-empty one for the greeting.
                if response.get("audio_content"):
                    welcome_audio = response["audio_content"]

            # If the greeting turn had not completed within the wait window, the
            # buffered frames were not yet flushed. Flush and pick them up so the
            # caller still hears the greeting.
            if not welcome_audio and stream_session._flush_audio_buffer():
                for response in stream_session.drain_responses():
                    if response.get("audio_content"):
                        welcome_audio = response["audio_content"]

            return self.create_session_start_response(
                conversation_id=conversation_id,
                text=welcome_text,
                audio_content=welcome_audio,
            )
        except Exception as exc:
            self.logger.error(
                f"[GECX] Error starting conversation {conversation_id}: {exc}",
                exc_info=True,
            )
            return self.create_error_response(
                conversation_id=conversation_id,
                error_message=f"Failed to start GECX conversation: {exc}",
            )

    def send_message(
        self, conversation_id: str, message_data: Dict[str, Any]
    ) -> Generator[Dict[str, Any], None, None]:
        with self.sessions_lock:
            stream_session = self.streaming_sessions.get(conversation_id)

        if not stream_session:
            self.logger.error(
                f"[GECX] No active stream for conversation: {conversation_id}"
            )
            return

        message_type = message_data.get("input_type") or message_data.get("type", "audio")

        try:
            if message_type == "audio":
                yield from self._handle_audio_input(
                    conversation_id, stream_session, message_data
                )
            elif message_type == "text":
                yield from self._handle_text_input(
                    conversation_id, stream_session, message_data
                )
            elif message_type == "event":
                yield from self._handle_event_input(
                    conversation_id, stream_session, message_data
                )
            else:
                yield self.create_error_response(
                    conversation_id=conversation_id,
                    error_message=f"Unknown message type: {message_type}",
                )
        except Exception as exc:
            self.logger.error(
                f"[GECX] Error processing message for {conversation_id}: {exc}",
                exc_info=True,
            )
            yield self.create_error_response(
                conversation_id=conversation_id,
                error_message=f"Error processing message: {exc}",
            )

    def _handle_audio_input(
        self,
        conversation_id: str,
        stream_session: GECXStreamingSession,
        message_data: Dict[str, Any],
    ) -> Generator[Dict[str, Any], None, None]:
        audio_data_raw = message_data.get("audio") or message_data.get("audio_data", b"")
        audio_chunk = self.extract_audio_data(audio_data_raw, conversation_id, self.logger)
        if not audio_chunk:
            return

        detected_rate, detected_encoding = self._resolve_input_format(
            audio_chunk, message_data, conversation_id
        )
        target_rate = self.input_sample_rate_hertz
        target_encoding = self._normalize_encoding_name(self.input_audio_encoding)

        if detected_rate != target_rate or detected_encoding != target_encoding:
            audio_chunk = self._convert_audio_format(
                audio_chunk,
                from_rate=detected_rate,
                from_encoding=detected_encoding,
                to_rate=target_rate,
                to_encoding=target_encoding,
                conversation_id=conversation_id,
            )

        stream_session.enqueue_audio(audio_chunk)

        for response in stream_session.drain_responses():
            yield response

    def _handle_text_input(
        self,
        conversation_id: str,
        stream_session: GECXStreamingSession,
        message_data: Dict[str, Any],
    ) -> Generator[Dict[str, Any], None, None]:
        text = message_data.get("text", "")
        if not text:
            return
        stream_session.enqueue_text(text)
        for response in stream_session.wait_for_responses(timeout=10.0):
            yield response

    def _handle_event_input(
        self,
        conversation_id: str,
        stream_session: GECXStreamingSession,
        message_data: Dict[str, Any],
    ) -> Generator[Dict[str, Any], None, None]:
        event_name = message_data.get("event", "")
        if not event_name and message_data.get("event_data"):
            event_name = message_data["event_data"].get("name", "")
        if not event_name:
            return
        stream_session.enqueue_event(event_name)
        for response in stream_session.wait_for_responses(timeout=10.0):
            yield response

    def end_conversation(
        self, conversation_id: str, message_data: Optional[Dict[str, Any]] = None
    ) -> None:
        self.logger.info(f"[GECX] Ending conversation: {conversation_id}")
        with self.sessions_lock:
            stream_session = self.streaming_sessions.pop(conversation_id, None)
            self.detected_formats.pop(conversation_id, None)

        if stream_session:
            stream_session.stop()

    def convert_wxcc_to_vendor(self, grpc_data: Any) -> Dict[str, Any]:
        return {"data": grpc_data, "converted_for": "gecx"}

    def convert_vendor_to_wxcc(self, vendor_data: Any) -> Any:
        return vendor_data

    # --- Audio helpers (adapted from Dialogflow CX connector) ---

    @staticmethod
    def _normalize_encoding_name(encoding: str) -> str:
        name = encoding.upper().replace("AUDIO_ENCODING_", "")
        if name in ("LINEAR16", "LINEAR_16"):
            return "LINEAR_16"
        if name == "MULAW":
            return "MULAW"
        return name

    def _resolve_input_format(
        self,
        audio_chunk: bytes,
        message_data: Dict[str, Any],
        conversation_id: str,
    ) -> Tuple[int, str]:
        if message_data.get("sample_rate_hertz"):
            rate = int(message_data["sample_rate_hertz"])
            encoding = self._encoding_from_proto(message_data.get("encoding"))
            self.detected_formats[conversation_id] = (rate, encoding)
            return rate, encoding

        return self._detect_audio_format(audio_chunk, conversation_id)

    @staticmethod
    def _encoding_from_proto(encoding_value: Any) -> str:
        if encoding_value is None:
            return "MULAW"
        if isinstance(encoding_value, str):
            return GECXConnector._normalize_encoding_name(encoding_value)
        # WxCC VoiceInput.VoiceEncoding enum int
        proto_map = {1: "LINEAR_16", 2: "MULAW", 3: "ALAW"}
        return proto_map.get(int(encoding_value), "MULAW")

    def _detect_audio_format(
        self, audio_chunk: bytes, conversation_id: str
    ) -> Tuple[int, str]:
        if self.force_input_format == "wxcc":
            self.detected_formats[conversation_id] = (8000, "MULAW")
            return 8000, "MULAW"
        if self.force_input_format == "test":
            rate = self.input_sample_rate_hertz
            enc = "LINEAR_16" if rate >= 16000 else "MULAW"
            self.detected_formats[conversation_id] = (rate, enc)
            return rate, enc

        if conversation_id in self.detected_formats:
            return self.detected_formats[conversation_id]

        chunk_size = len(audio_chunk)
        if chunk_size < 100:
            return 8000, "MULAW"
        if 600 <= chunk_size <= 800:
            sample_rate, encoding = 8000, "MULAW"
        elif chunk_size > 1000:
            sample_rate = self.input_sample_rate_hertz
            encoding = "LINEAR_16" if sample_rate >= 16000 else "MULAW"
        else:
            sample_rate, encoding = 8000, "MULAW"

        self.detected_formats[conversation_id] = (sample_rate, encoding)
        return sample_rate, encoding

    @staticmethod
    def _mulaw_to_linear(mulaw_data: bytes) -> bytes:
        mulaw_bias = 33
        mulaw_max = 0x1FFF
        linear_data = []
        for mulaw_byte in mulaw_data:
            mulaw_byte = ~mulaw_byte & 0xFF
            sign = (mulaw_byte & 0x80) >> 7
            segment = (mulaw_byte & 0x70) >> 4
            quantization = mulaw_byte & 0x0F
            linear = ((quantization << 1) + mulaw_bias) << segment
            linear = min(linear, mulaw_max)
            if sign:
                linear = -linear
            linear_data.append(struct.pack("<h", linear))
        return b"".join(linear_data)

    @staticmethod
    def _resample_audio(
        audio_data: bytes, from_rate: int, to_rate: int, sample_width: int
    ) -> bytes:
        ratio = from_rate / to_rate
        if sample_width == 1:
            samples = list(audio_data)
        else:
            samples = list(struct.unpack(f"<{len(audio_data) // 2}h", audio_data))

        resampled = []
        num_output_samples = int(len(samples) / ratio) if ratio else 0
        for i in range(num_output_samples):
            src_index = i * ratio
            src_index_int = int(src_index)
            fraction = src_index - src_index_int
            if src_index_int + 1 < len(samples):
                sample = int(
                    samples[src_index_int] * (1 - fraction)
                    + samples[src_index_int + 1] * fraction
                )
            else:
                sample = samples[src_index_int]
            resampled.append(sample)

        if sample_width == 1:
            return bytes(resampled)
        return struct.pack(f"<{len(resampled)}h", *resampled)

    def _convert_audio_format(
        self,
        audio_data: bytes,
        from_rate: int,
        from_encoding: str,
        to_rate: int,
        to_encoding: str,
        conversation_id: str,
    ) -> bytes:
        try:
            converted = audio_data

            if from_encoding == "MULAW" and to_encoding == "LINEAR_16":
                if AUDIOOP_AVAILABLE:
                    converted = audioop.ulaw2lin(audio_data, 2)
                else:
                    converted = self._mulaw_to_linear(audio_data)
            elif from_encoding == "LINEAR_16" and to_encoding == "MULAW":
                if AUDIOOP_AVAILABLE:
                    converted = audioop.lin2ulaw(audio_data, 2)

            if from_rate != to_rate:
                width = 2 if to_encoding == "LINEAR_16" else 1
                if AUDIOOP_AVAILABLE:
                    converted, _ = audioop.ratecv(
                        converted, width, 1, from_rate, to_rate, None
                    )
                else:
                    converted = self._resample_audio(
                        converted, from_rate, to_rate, width
                    )

            return converted
        except Exception as exc:
            self.logger.error(
                f"[{conversation_id}] [GECX] Audio conversion failed: {exc}"
            )
            return audio_data
