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
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Generator, Iterator, Optional, Tuple

try:
    import audioop

    AUDIOOP_AVAILABLE = True
except ImportError:
    AUDIOOP_AVAILABLE = False
    audioop = None

try:
    import pickle

    from google.api_core import client_options as client_options_lib
    from google.api_core import exceptions as google_exceptions
    from google.auth.transport.requests import Request
    from google.cloud import ces_v1
    from google.oauth2 import service_account
    from google.oauth2.credentials import Credentials as OAuth2Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

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

from .i_vendor_connector import IVendorConnector

# CES session IDs: [a-zA-Z0-9][a-zA-Z0-9-_]{4,62}
_SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9\-_]{4,62}$")

# Sentinel objects for the inbound control queue
_AUDIO_END = object()
_STREAM_STOP = object()


class GECXTerminalReason(str, Enum):
    """Reasons a GECX streaming session can reach a terminal state."""

    NORMAL_END = "normal_end"
    ESCALATION = "escalation"
    TIMEOUT = "timeout"
    GO_AWAY = "go_away"
    CLIENT_CANCELLED = "client_cancelled"
    CLIENT_HALF_CLOSE = "client_half_close"
    STREAM_ERROR = "stream_error"
    EXPLICIT_SHUTDOWN = "explicit_shutdown"


class GECXTerminalOutcome(str, Enum):
    """Response behavior selected by a GECX terminal decision."""

    TRANSFER = "transfer"
    SESSION_END = "session_end"
    SILENT = "silent"


@dataclass(frozen=True)
class GECXTerminalDecision:
    """The immutable first terminal decision for a GECX session."""

    reason: GECXTerminalReason
    outcome: GECXTerminalOutcome
    source: str
    metadata: Dict[str, Any]
    decided_at: float


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
        async_response_sink: Optional[
            Callable[[Dict[str, Any]], bool]
        ] = None,
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
        self._turn_completed = threading.Event()
        self._stream_error: Optional[str] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        # Server callbacks can re-enter lifecycle helpers such as terminate()
        # while the callback holds the turn-state lock. An RLock keeps that
        # atomic without deadlocking the callback thread.
        self._lifecycle_lock = threading.RLock()
        self._terminal_decision: Optional[GECXTerminalDecision] = None
        self._join_attempted = False
        self._started_at = time.monotonic()
        self._async_response_sink = async_response_sink
        self._turn_response_waiters = 0
        # Reserve the greeting for start_conversation's pull iterator even if
        # CES emits it before that generator begins iterating.
        self._caller_response_expected = bool(initial_message)
        self._output_turn_active = False
        # CES streams text and TTS output separately during an agent turn. Text
        # is retained only as a transcript/fallback; each audio frame is emitted
        # immediately as raw telephony audio so WxCC can begin playback before
        # CES marks the turn complete.
        self._text_buffer: list[str] = []
        self._turn_audio_emitted = False
        self._turn_audio_chunk_count = 0
        self._turn_audio_bytes = 0
        self._turn_started_at = time.monotonic()
        # Inspect only the start of each CES turn for anomalously long,
        # low-energy audio before synthesized speech. Normal short frames keep
        # their direct streaming path.
        self._output_audio_gate_state = (
            "inspect" if connector.suppress_long_leading_audio else "open"
        )
        self._output_audio_gate_seen_bytes = 0
        self._output_audio_gate_buffer = bytearray()
        self._input_lock = threading.Lock()
        self._input_audio_buffer = bytearray()
        self._input_resume_buffer = bytearray()
        self._input_turn_active = False
        self._input_turn_paused = False
        # CES can autonomously start a no-input prompt immediately before the
        # gateway detects caller speech. Keep that stale output isolated until
        # CES acknowledges the committed caller audio with recognition or an
        # interruption signal.
        self._awaiting_input_ack = False
        self._suppressed_pre_input_messages = 0
        self._suppressed_pre_input_audio_bytes = 0
        self._suppressed_pre_input_text_chars = 0

    def set_async_response_sink(
        self, response_sink: Callable[[Dict[str, Any]], bool]
    ) -> None:
        """Attach the active WxCC stream and flush queued autonomous output."""
        with self._lifecycle_lock:
            self._async_response_sink = response_sink
            if self._turn_response_waiters or self._caller_response_expected:
                return

            while True:
                try:
                    response = self.outbound_queue.get_nowait()
                except queue.Empty:
                    break
                if not response_sink(response):
                    self.outbound_queue.put(response)
                    break

    def clear_async_response_sink(
        self, response_sink: Callable[[Dict[str, Any]], bool]
    ) -> None:
        """Detach only the WxCC stream that currently owns the session."""
        with self._lifecycle_lock:
            if self._async_response_sink is response_sink:
                self._async_response_sink = None

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

    @property
    def terminal_decision(self) -> Optional[GECXTerminalDecision]:
        """Return the session's first terminal decision, if one exists."""
        with self._lifecycle_lock:
            return self._terminal_decision

    @property
    def is_terminal(self) -> bool:
        """Return whether the session has made a terminal decision."""
        return self.terminal_decision is not None

    def stop(
        self,
        reason: GECXTerminalReason = GECXTerminalReason.EXPLICIT_SHUTDOWN,
        source: str = "connector_stop",
    ) -> None:
        """Terminate silently and wait once for the stream thread."""
        self.terminate(
            reason=reason,
            outcome=GECXTerminalOutcome.SILENT,
            source=source,
        )

        with self._lifecycle_lock:
            if self._join_attempted:
                return
            self._join_attempted = True
            thread = self._thread

        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=10)
            if thread.is_alive():
                self.logger.error(
                    "gecx_session_join_timeout conversation_id=%s session=%s "
                    "terminal_reason=%s",
                    self.conversation_id,
                    self.session_path,
                    self.terminal_decision.reason.value,
                )

    def enqueue_audio(self, audio_chunk: bytes) -> bool:
        """Buffer caller audio until gateway VAD closes the complete turn."""
        if not audio_chunk:
            return False
        with self._lifecycle_lock:
            if self._terminal_decision is not None:
                self._log_late_input("audio")
                return False
            with self._input_lock:
                if self._input_turn_paused:
                    self._input_resume_buffer.extend(audio_chunk)
                    resume_preroll_bytes = self.connector.input_audio_bytes_for_ms(
                        self.connector.input_pause_preroll_ms
                    )
                    if len(self._input_resume_buffer) > resume_preroll_bytes:
                        if resume_preroll_bytes:
                            del self._input_resume_buffer[:-resume_preroll_bytes]
                        else:
                            self._input_resume_buffer.clear()
                else:
                    self._input_audio_buffer.extend(audio_chunk)
                if not self._input_turn_active and not self._input_turn_paused:
                    pre_roll_bytes = self.connector.input_audio_bytes_for_ms(
                        self.connector.input_preroll_ms
                    )
                    if len(self._input_audio_buffer) > pre_roll_bytes:
                        if pre_roll_bytes:
                            del self._input_audio_buffer[:-pre_roll_bytes]
                        else:
                            self._input_audio_buffer.clear()
        return True

    def pause_input_turn(self, silence_ms: int) -> bool:
        """Hold a possible turn end and remove its endpoint-triggering silence."""
        with self._lifecycle_lock:
            if self._terminal_decision is not None:
                self._log_late_input("speech_pause")
                return False
            with self._input_lock:
                if not self._input_turn_active:
                    return False
                silence_bytes = self.connector.input_audio_bytes_for_ms(silence_ms)
                if silence_bytes:
                    del self._input_audio_buffer[
                        -min(silence_bytes, len(self._input_audio_buffer)) :
                    ]
                self._input_resume_buffer.clear()
                self._input_turn_paused = True
        return True

    def resume_input_turn(self) -> bool:
        """Merge bounded pre-roll from a resumed speech segment into this turn."""
        with self._lifecycle_lock:
            if self._terminal_decision is not None:
                self._log_late_input("speech_resume")
                return False
            with self._input_lock:
                if not self._input_turn_paused:
                    return False
                self._input_audio_buffer.extend(self._input_resume_buffer)
                self._input_resume_buffer.clear()
                self._input_turn_paused = False
                self._input_turn_active = True
        return True

    def enqueue_text(self, text: str) -> bool:
        """Queue a text turn for the CES stream."""
        if not text:
            return False
        with self._lifecycle_lock:
            if self._terminal_decision is not None:
                self._log_late_input("text")
                return False
            self.inbound_queue.put(("text", text))
        return True

    def enqueue_event(self, event_name: str) -> bool:
        """Queue an event for the CES stream."""
        if not event_name:
            return False
        with self._lifecycle_lock:
            if self._terminal_decision is not None:
                self._log_late_input("event")
                return False
            self.inbound_queue.put(("event", event_name))
        return True

    def end_audio_turn(self) -> bool:
        """Flush one gateway-delimited caller turn and endpointing silence."""
        with self._lifecycle_lock:
            if self._terminal_decision is not None:
                self._log_late_input("audio_end")
                return False
            with self._input_lock:
                turn_audio = bytes(self._input_audio_buffer)
                resume_audio = bytes(self._input_resume_buffer)
                self._input_audio_buffer.clear()
                self._input_audio_buffer.extend(resume_audio)
                self._input_resume_buffer.clear()
                self._input_turn_active = False
                self._input_turn_paused = False

            chunk_bytes = self.connector.input_audio_bytes_for_ms(100)
            if chunk_bytes <= 0:
                chunk_bytes = len(turn_audio) or 1
            for offset in range(0, len(turn_audio), chunk_bytes):
                self.inbound_queue.put(turn_audio[offset : offset + chunk_bytes])
            self.inbound_queue.put(_AUDIO_END)
        return True

    def _log_late_input(self, input_type: str) -> None:
        decision = self._terminal_decision
        self.logger.warning(
            "gecx_late_input_suppressed conversation_id=%s session=%s "
            "input_type=%s terminal_reason=%s terminal_outcome=%s",
            self.conversation_id,
            self.session_path,
            input_type,
            decision.reason.value if decision else "unknown",
            decision.outcome.value if decision else "unknown",
        )

    def drain_responses(self) -> list[Dict[str, Any]]:
        """Non-blocking drain of outbound connector responses."""
        responses: list[Dict[str, Any]] = []
        while True:
            try:
                responses.append(self.outbound_queue.get_nowait())
            except queue.Empty:
                break
        return responses

    def _publish_response_locked(self, response: Dict[str, Any]) -> bool:
        """Deliver a response to its active turn waiter or live WxCC stream."""
        is_autonomous = (
            self._turn_response_waiters == 0
            and not self._caller_response_expected
        )
        if is_autonomous and self._async_response_sink is not None:
            if self._async_response_sink(response):
                return True

        # Preserve the existing pull path for caller-owned turns and retain
        # autonomous output when the WxCC stream is temporarily detached.
        self.outbound_queue.put(response)
        return True

    def _mark_output_turn_started_locked(self) -> None:
        """Open a newly observed CES output turn and reset stale completion."""
        if self._output_turn_active:
            return
        self._output_turn_active = True
        self._turn_completed.clear()
        self._turn_started_at = time.monotonic()

    def begin_input_turn(self, *, expect_recognition: bool = False) -> bool:
        """Isolate the response turn when gateway VAD detects caller speech."""
        with self._lifecycle_lock:
            if self._terminal_decision is not None:
                self._log_late_input("speech_boundary")
                return False
            with self._input_lock:
                self._input_turn_active = True
                self._input_turn_paused = False
                self._input_resume_buffer.clear()
            with self._lock:
                discarded_chunks = self._turn_audio_chunk_count
                discarded_audio_bytes = self._turn_audio_bytes
                discarded_text_chars = sum(map(len, self._text_buffer))
                self._text_buffer = []
                self._turn_audio_emitted = False
                self._turn_audio_chunk_count = 0
                self._turn_audio_bytes = 0
                self._reset_output_audio_gate()
            discarded_responses = 0
            while True:
                try:
                    self.outbound_queue.get_nowait()
                    discarded_responses += 1
                except queue.Empty:
                    break
            self._turn_started_at = time.monotonic()
            self._turn_completed.clear()
            self._caller_response_expected = True
            self._output_turn_active = False
            self._awaiting_input_ack = expect_recognition
            self._suppressed_pre_input_messages = 0
            self._suppressed_pre_input_audio_bytes = 0
            self._suppressed_pre_input_text_chars = 0

        if any(
            (
                discarded_chunks,
                discarded_audio_bytes,
                discarded_text_chars,
                discarded_responses,
            )
        ):
            self.logger.info(
                "gecx_output_discarded_on_caller_start conversation_id=%s "
                "chunks=%d audio_bytes=%d text_chars=%d queued_responses=%d",
                self.conversation_id,
                discarded_chunks,
                discarded_audio_bytes,
                discarded_text_chars,
                discarded_responses,
            )
        return True

    def _acknowledge_caller_input_locked(self, source: str) -> None:
        """Open the post-input response turn after CES accepts caller audio."""
        if not self._awaiting_input_ack:
            return

        self._awaiting_input_ack = False
        self._turn_completed.clear()
        self._reset_output_audio_gate()
        self.logger.info(
            "gecx_caller_input_acknowledged conversation_id=%s source=%s "
            "suppressed_messages=%d suppressed_audio_bytes=%d "
            "suppressed_text_chars=%d",
            self.conversation_id,
            source,
            self._suppressed_pre_input_messages,
            self._suppressed_pre_input_audio_bytes,
            self._suppressed_pre_input_text_chars,
        )
        self._suppressed_pre_input_messages = 0
        self._suppressed_pre_input_audio_bytes = 0
        self._suppressed_pre_input_text_chars = 0

    def iter_turn_responses(
        self,
        timeout: float,
        *,
        terminal_grace_seconds: float = 0.0,
        terminate_on_timeout: bool = True,
    ) -> Iterator[Dict[str, Any]]:
        """Yield CES audio frames immediately, followed by exactly one FINAL."""
        with self._lifecycle_lock:
            self._turn_response_waiters += 1
        try:
            yield from self._iter_turn_responses(
                timeout,
                terminal_grace_seconds=terminal_grace_seconds,
                terminate_on_timeout=terminate_on_timeout,
            )
        finally:
            with self._lifecycle_lock:
                self._turn_response_waiters = max(
                    0, self._turn_response_waiters - 1
                )

    def _iter_turn_responses(
        self,
        timeout: float,
        *,
        terminal_grace_seconds: float = 0.0,
        terminate_on_timeout: bool = True,
    ) -> Iterator[Dict[str, Any]]:
        """Run the pull-based response loop while a gateway turn owns output."""
        deadline = time.monotonic() + max(0.0, timeout)
        terminal_grace_deadline: Optional[float] = None

        while True:
            now = time.monotonic()
            completed = self._turn_completed.is_set()

            if not completed and now >= deadline:
                self.logger.warning(
                    "[%s] [GECX] Timed out after %.1fs waiting for turn completion",
                    self.conversation_id,
                    timeout,
                )
                if terminate_on_timeout:
                    self.terminate(
                        reason=GECXTerminalReason.TIMEOUT,
                        outcome=GECXTerminalOutcome.SESSION_END,
                        source="turn_response_timeout",
                        metadata={"timeout_seconds": timeout},
                    )
                    continue
                return

            try:
                response = self.outbound_queue.get_nowait()
            except queue.Empty:
                response = None
            if response is not None:
                yield response
                if (
                    response.get("message_type") in {"transfer", "session_end"}
                    or response.get("response_type") == "final"
                ):
                    return
                continue

            if completed and self.outbound_queue.empty():
                if self.is_terminal:
                    return

                buffered_text = self._active_text()
                may_have_terminal = self.connector.may_have_delayed_terminal(
                    buffered_text
                )
                if (
                    may_have_terminal
                    and terminal_grace_seconds > 0
                    and terminal_grace_deadline is None
                ):
                    terminal_grace_deadline = (
                        now + max(0.0, terminal_grace_seconds)
                    )
                    self.logger.info(
                        "[%s] [GECX] Waiting up to %.1fs for a terminal event "
                        "after streamed announcement audio",
                        self.conversation_id,
                        terminal_grace_seconds,
                    )

                if (
                    terminal_grace_deadline is None
                    or now >= terminal_grace_deadline
                ):
                    final_response = self._finish_normal_turn()
                    if final_response is not None:
                        yield final_response
                    return

            wait_deadline = deadline
            if completed and terminal_grace_deadline is not None:
                wait_deadline = terminal_grace_deadline
            wait_seconds = min(0.1, max(0.0, wait_deadline - now))
            if wait_seconds <= 0:
                continue

            try:
                response = self.outbound_queue.get(timeout=wait_seconds)
            except queue.Empty:
                continue

            yield response
            if (
                response.get("message_type") in {"transfer", "session_end"}
                or response.get("response_type") == "final"
            ):
                return

    def _active_text(self) -> str:
        """Return the current CES text without exposing mutable session state."""
        with self._lock:
            return "".join(self._text_buffer)

    def _finish_normal_turn(self) -> Optional[Dict[str, Any]]:
        """Commit the sole non-terminal FINAL after all streamed audio chunks."""
        with self._lifecycle_lock:
            if self._terminal_decision is not None:
                return None
            with self._lock:
                buffered_text = "".join(self._text_buffer)
                audio_emitted = self._turn_audio_emitted
                chunk_count = self._turn_audio_chunk_count
                audio_bytes = self._turn_audio_bytes
                self._text_buffer = []
                self._turn_audio_emitted = False
                self._turn_audio_chunk_count = 0
                self._turn_audio_bytes = 0
                self._reset_output_audio_gate()
                self._output_turn_active = False
                self._caller_response_expected = False

        self.logger.info(
            "gecx_streamed_turn_complete conversation_id=%s chunks=%d "
            "audio_bytes=%d elapsed_seconds=%.3f terminal=false",
            self.conversation_id,
            chunk_count,
            audio_bytes,
            time.monotonic() - self._turn_started_at,
        )
        return self.connector.create_response(
            conversation_id=self.conversation_id,
            message_type=(
                "silence" if audio_emitted or not buffered_text else "agent_response"
            ),
            text="" if audio_emitted else buffered_text,
            barge_in_enabled=False,
            response_type="final",
        )

    def terminate(
        self,
        reason: GECXTerminalReason,
        outcome: GECXTerminalOutcome,
        source: str,
        metadata: Optional[Dict[str, Any]] = None,
        response_text: str = "",
    ) -> bool:
        """Make the session's terminal decision exactly once.

        The winning call rejects future input, preserves audio CHUNK responses
        already queued for the gateway, half-closes the CES request stream,
        wakes response waiters, and optionally queues one canonical terminal
        FINAL after those chunks. Later calls are no-ops.
        """
        terminal_metadata = dict(metadata or {})
        decided_at = time.monotonic()

        with self._lifecycle_lock:
            if self._terminal_decision is not None:
                current = self._terminal_decision
                self.logger.warning(
                    "gecx_duplicate_terminal_suppressed conversation_id=%s "
                    "session=%s attempted_reason=%s attempted_outcome=%s "
                    "attempted_source=%s terminal_reason=%s terminal_outcome=%s "
                    "terminal_source=%s",
                    self.conversation_id,
                    self.session_path,
                    reason.value,
                    outcome.value,
                    source,
                    current.reason.value,
                    current.outcome.value,
                    current.source,
                )
                return False

            decision = GECXTerminalDecision(
                reason=reason,
                outcome=outcome,
                source=source,
                metadata=terminal_metadata,
                decided_at=decided_at,
            )
            self._terminal_decision = decision
            self._stop_event.set()

            with self._input_lock:
                self._input_audio_buffer.clear()
                self._input_resume_buffer.clear()
                self._input_turn_active = False
                self._input_turn_paused = False
            with self._lock:
                buffered_text = "".join(self._text_buffer)
                audio_emitted = self._turn_audio_emitted
                chunk_count = self._turn_audio_chunk_count
                audio_bytes = self._turn_audio_bytes
                self._text_buffer = []
                self._turn_audio_emitted = False
                self._turn_audio_chunk_count = 0
                self._turn_audio_bytes = 0
                self._reset_output_audio_gate()
                self._output_turn_active = False
                self._caller_response_expected = False

            # Queue the stop sentinel exactly once. The request generator also
            # checks terminal state after dequeuing to close the final race where
            # it already pulled caller audio as termination was decided.
            self.inbound_queue.put(_STREAM_STOP)

            terminal_response = self._create_terminal_response(
                decision,
                response_text=(
                    ""
                    if audio_emitted
                    else (buffered_text or response_text or None)
                ),
            )
            if terminal_response is not None:
                self._publish_response_locked(terminal_response)

            # Set completion only after the terminal response is visible so a
            # waiter cannot wake and drain the queue too early.
            self._turn_completed.set()

        self.logger.info(
            "gecx_terminal_decision conversation_id=%s session=%s reason=%s "
            "outcome=%s source=%s elapsed_seconds=%.3f chunks=%d "
            "audio_bytes=%d metadata_keys=%s end_session_metadata_keys=%s",
            self.conversation_id,
            self.session_path,
            reason.value,
            outcome.value,
            source,
            decided_at - self._started_at,
            chunk_count,
            audio_bytes,
            sorted(terminal_metadata),
            sorted(
                terminal_metadata.get("end_session", {})
                if isinstance(terminal_metadata.get("end_session"), dict)
                else {}
            ),
        )
        return True

    def _create_terminal_response(
        self,
        decision: GECXTerminalDecision,
        response_text: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Build one canonical connector response for a terminal decision."""
        if decision.outcome == GECXTerminalOutcome.SILENT:
            return None
        if decision.outcome == GECXTerminalOutcome.TRANSFER:
            return self.connector.create_response(
                conversation_id=self.conversation_id,
                message_type="transfer",
                text=(
                    "Transferring you to an agent."
                    if response_text is None
                    else response_text
                ),
                barge_in_enabled=False,
                response_type="final",
            )
        return self.connector.create_response(
            conversation_id=self.conversation_id,
            message_type="session_end",
            text=response_text or "",
            barge_in_enabled=False,
            response_type="final",
        )

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

        if self.initial_message and not self.is_terminal:
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
            if self.is_terminal:
                break
            if item is _AUDIO_END:
                for audio_chunk in self.connector.endpointing_silence_chunks():
                    if self.is_terminal:
                        break
                    yield ces_v1.BidiSessionClientMessage(
                        realtime_input=ces_v1.SessionInput(audio=audio_chunk)
                    )
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
            if self.is_terminal:
                self.logger.debug(
                    "gecx_stream_closed_after_terminal conversation_id=%s "
                    "session=%s error=%r",
                    self.conversation_id,
                    self.session_path,
                    exc,
                )
            else:
                self.logger.error(
                    "gecx_stream_error conversation_id=%s session=%s error=%r",
                    self.conversation_id,
                    self.session_path,
                    exc,
                    exc_info=True,
                )
                self._stream_error = str(exc)
                self.terminate(
                    reason=GECXTerminalReason.STREAM_ERROR,
                    outcome=GECXTerminalOutcome.SESSION_END,
                    source="bidi_run_session_exception",
                    metadata={"error": str(exc)},
                )
        finally:
            if not self.is_terminal:
                self._stream_error = "CES response stream closed without EndSession"
                self.terminate(
                    reason=GECXTerminalReason.STREAM_ERROR,
                    outcome=GECXTerminalOutcome.SESSION_END,
                    source="bidi_run_session_closed",
                    metadata={"error": self._stream_error},
                )
            self._stream_started.set()
            self._turn_completed.set()

    def _handle_server_message(self, message: Any) -> None:
        """Map one CES message atomically against gateway turn boundaries."""
        with self._lifecycle_lock:
            self._handle_server_message_locked(message)

    def _handle_server_message_locked(self, message: Any) -> None:
        """Map a CES server message while holding the lifecycle lock."""
        conversation_id = self.conversation_id
        turn_completed = False

        if self.is_terminal:
            decision = self.terminal_decision
            self.logger.warning(
                "gecx_late_server_message_suppressed conversation_id=%s "
                "session=%s terminal_reason=%s terminal_outcome=%s",
                conversation_id,
                self.session_path,
                decision.reason.value,
                decision.outcome.value,
            )
            return

        if message.recognition_result:
            self._acknowledge_caller_input_locked("recognition_result")
            transcript = message.recognition_result.transcript.strip()
            if transcript:
                self.logger.debug(
                    f"[{conversation_id}] [GECX] STT: '{transcript}'"
                )

        if message.interruption_signal:
            self.logger.info(f"[{conversation_id}] [GECX] Barge-in interruption signal")
            # Keep lifecycle -> audio locking consistent with terminate() so a
            # concurrent interruption cannot erase the winning terminal response.
            with self._lifecycle_lock:
                if self._terminal_decision is None:
                    with self._lock:
                        self._text_buffer = []
                        self._turn_audio_emitted = False
                        self._turn_audio_chunk_count = 0
                        self._turn_audio_bytes = 0
                        self._reset_output_audio_gate()
                    while True:
                        try:
                            self.outbound_queue.get_nowait()
                        except queue.Empty:
                            break

        if message.session_output:
            output = message.session_output
            has_terminal_output = bool(output.end_session)

            audio_bytes = self._decode_output_audio(output.audio)
            if self._awaiting_input_ack and not has_terminal_output:
                self._suppressed_pre_input_messages += 1
                self._suppressed_pre_input_audio_bytes += len(audio_bytes)
                self._suppressed_pre_input_text_chars += len(output.text or "")
                if output.turn_completed:
                    self.logger.info(
                        "gecx_pre_input_output_suppressed conversation_id=%s "
                        "messages=%d audio_bytes=%d text_chars=%d",
                        conversation_id,
                        self._suppressed_pre_input_messages,
                        self._suppressed_pre_input_audio_bytes,
                        self._suppressed_pre_input_text_chars,
                    )
            else:
                if output.text or audio_bytes:
                    self._mark_output_turn_started_locked()
                if output.text:
                    self.logger.info(
                        f"[{conversation_id}] [GECX] Agent: '{output.text}'"
                    )
                    self._buffer_active_text(output.text)

                if audio_bytes:
                    playable_audio = self._filter_leading_output_audio(audio_bytes)
                    if playable_audio:
                        self._emit_active_audio_chunk(playable_audio)

                # Audio frames are already queued as CHUNK responses. Completion
                # only releases the response iterator to emit its sole FINAL.
                if output.turn_completed and not has_terminal_output:
                    turn_completed = True

            if has_terminal_output:
                self._handle_end_session(
                    conversation_id,
                    output.end_session,
                )
                turn_completed = True

        if message.end_session:
            self._handle_end_session(conversation_id, message.end_session)
            turn_completed = True

        if message.go_away:
            self.terminate(
                reason=GECXTerminalReason.GO_AWAY,
                outcome=GECXTerminalOutcome.SESSION_END,
                source="ces_go_away",
            )
            turn_completed = True

        if turn_completed:
            self._turn_completed.set()
            if (
                not self.is_terminal
                and self._turn_response_waiters == 0
                and not self._caller_response_expected
                and self._output_turn_active
            ):
                final_response = self._finish_normal_turn()
                if final_response is not None:
                    self._publish_response_locked(final_response)

    def _enqueue_active_response(self, response: Dict[str, Any]) -> bool:
        """Queue a non-terminal response only while the session is active."""
        with self._lifecycle_lock:
            if self._terminal_decision is not None:
                return False
            self.outbound_queue.put(response)
        return True

    def _reset_output_audio_gate(self) -> None:
        """Reset guarded leading-audio inspection for the next CES turn."""
        self._output_audio_gate_state = (
            "inspect" if self.connector.suppress_long_leading_audio else "open"
        )
        self._output_audio_gate_seen_bytes = 0
        self._output_audio_gate_buffer.clear()

    @staticmethod
    def _mulaw_rms(audio_bytes: bytes) -> int:
        """Return the RMS level of raw G.711 mu-law samples."""
        if not audio_bytes:
            return 0
        if AUDIOOP_AVAILABLE:
            return audioop.rms(audioop.ulaw2lin(audio_bytes, 2), 2)

        total = 0
        for sample in audio_bytes:
            inverted = (~sample) & 0xFF
            magnitude = (((inverted & 0x0F) << 3) + 0x84) << (
                (inverted & 0x70) >> 4
            )
            linear = magnitude - 0x84
            total += linear * linear
        return int((total / len(audio_bytes)) ** 0.5)

    def _find_output_speech_offset(self, audio_bytes: bytes) -> Optional[int]:
        """Find the first sustained speech-like mu-law frame in audio bytes."""
        frame_bytes = self.connector.output_speech_frame_bytes
        required_frames = self.connector.output_speech_start_frames
        consecutive = 0

        for offset in range(0, len(audio_bytes) - frame_bytes + 1, frame_bytes):
            frame = audio_bytes[offset : offset + frame_bytes]
            if self._mulaw_rms(frame) >= self.connector.output_speech_rms_threshold:
                consecutive += 1
                if consecutive >= required_frames:
                    return offset - ((required_frames - 1) * frame_bytes)
            else:
                consecutive = 0
        return None

    def _open_output_audio_gate(
        self,
        audio_bytes: bytes,
        speech_offset: int,
    ) -> bytes:
        """Open the gate at detected speech while retaining bounded pre-roll."""
        start_offset = max(
            0,
            speech_offset - self.connector.output_speech_preroll_bytes,
        )
        playable_audio = audio_bytes[start_offset:]
        dropped_bytes = max(
            0,
            self._output_audio_gate_seen_bytes - len(playable_audio),
        )
        self._output_audio_gate_state = "open"
        self._output_audio_gate_buffer.clear()

        self.logger.warning(
            "gecx_leading_audio_suppressed conversation_id=%s "
            "dropped_bytes=%d dropped_seconds=%.3f speech_rms_threshold=%d",
            self.conversation_id,
            dropped_bytes,
            dropped_bytes / self.connector.output_sample_rate_hertz,
            self.connector.output_speech_rms_threshold,
        )
        return playable_audio

    def _filter_leading_output_audio(self, audio_bytes: bytes) -> bytes:
        """Suppress only anomalously long low-energy audio before CES speech."""
        if self._output_audio_gate_state == "open":
            return audio_bytes

        if self._output_audio_gate_state == "inspect":
            self._output_audio_gate_seen_bytes = len(audio_bytes)
            speech_offset = self._find_output_speech_offset(audio_bytes)
            minimum_lead_bytes = self.connector.output_leading_audio_min_bytes

            if speech_offset is not None:
                if speech_offset >= minimum_lead_bytes:
                    return self._open_output_audio_gate(audio_bytes, speech_offset)
                self._output_audio_gate_state = "open"
                return audio_bytes

            if len(audio_bytes) < minimum_lead_bytes:
                # Preserve short natural pauses and the normal CES framing path.
                self._output_audio_gate_state = "open"
                return audio_bytes

            self._output_audio_gate_state = "gating"
            keep_bytes = self.connector.output_audio_gate_tail_bytes
            self._output_audio_gate_buffer.extend(audio_bytes[-keep_bytes:])
            self.logger.warning(
                "gecx_long_leading_audio_detected conversation_id=%s "
                "frame_bytes=%d frame_seconds=%.3f speech_rms_threshold=%d",
                self.conversation_id,
                len(audio_bytes),
                len(audio_bytes) / self.connector.output_sample_rate_hertz,
                self.connector.output_speech_rms_threshold,
            )
            return b""

        previous_tail = bytes(self._output_audio_gate_buffer)
        combined_audio = previous_tail + audio_bytes
        self._output_audio_gate_seen_bytes += len(audio_bytes)
        speech_offset = self._find_output_speech_offset(combined_audio)
        if speech_offset is not None:
            return self._open_output_audio_gate(combined_audio, speech_offset)

        keep_bytes = self.connector.output_audio_gate_tail_bytes
        self._output_audio_gate_buffer.clear()
        self._output_audio_gate_buffer.extend(combined_audio[-keep_bytes:])
        return b""

    def _emit_active_audio_chunk(self, audio_bytes: bytes) -> bool:
        """Publish one raw CES audio frame as a BYOVA CHUNK response."""
        with self._lifecycle_lock:
            if self._terminal_decision is not None:
                return False
            autonomous_output = (
                self._turn_response_waiters == 0
                and not self._caller_response_expected
            )
            with self._lock:
                self._turn_audio_emitted = True
                self._turn_audio_chunk_count += 1
                self._turn_audio_bytes += len(audio_bytes)
                chunk_index = self._turn_audio_chunk_count
                total_bytes = self._turn_audio_bytes
            response = self.connector.create_response(
                conversation_id=self.conversation_id,
                message_type="audio",
                audio_content=audio_bytes,
                # CES no-input prompts can remain open while waiting for the
                # caller. They must allow WxCC to keep forwarding caller audio.
                barge_in_enabled=autonomous_output,
                response_type="chunk",
            )
            self._publish_response_locked(response)

        if chunk_index == 1:
            self.logger.info(
                "gecx_first_audio_chunk conversation_id=%s bytes=%d "
                "elapsed_seconds=%.3f delivery_mode=%s "
                "barge_in_enabled=%s",
                self.conversation_id,
                len(audio_bytes),
                time.monotonic() - self._turn_started_at,
                "async" if autonomous_output else "turn",
                autonomous_output,
            )
        else:
            self.logger.debug(
                "[%s] [GECX] Audio chunk %d: %d bytes (%d total)",
                self.conversation_id,
                chunk_index,
                len(audio_bytes),
                total_bytes,
            )
        return True

    def _buffer_active_text(self, text: str) -> bool:
        """Buffer CES text until its matching audio turn is complete."""
        with self._lifecycle_lock:
            if self._terminal_decision is not None:
                return False
            with self._lock:
                self._text_buffer.append(text)
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

        # CES documents this exact flag for escalated EndSession messages. Keep
        # it ahead of configurable aliases so the supported contract is obvious.
        escalated = lowered.get("session_escalated")
        if (
            escalated is True
            or (
                isinstance(escalated, (int, float))
                and not isinstance(escalated, bool)
                and escalated != 0
            )
            or (
                isinstance(escalated, str)
                and escalated.strip().lower() in truthy
            )
        ):
            return True, str(lowered.get("reason", "session_escalated"))

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

    def _handle_end_session(
        self,
        conversation_id: str,
        end_obj: Any,
        response_text: str = "",
    ) -> None:
        metadata = self._metadata_to_dict(end_obj)

        self.logger.info(
            "[%s] [GECX] EndSession metadata keys: %s",
            conversation_id,
            sorted(metadata),
        )
        if self.connector.log_raw_terminal_metadata_debug:
            self.logger.debug(
                "[%s] [GECX] Raw EndSession metadata: %s",
                conversation_id,
                metadata,
            )

        is_transfer, reason = self._detect_transfer(metadata)
        if is_transfer:
            self.terminate(
                reason=GECXTerminalReason.ESCALATION,
                outcome=GECXTerminalOutcome.TRANSFER,
                source="ces_end_session",
                metadata={
                    "transfer_reason": reason or "agent_requested_transfer",
                    "end_session": metadata,
                },
                response_text=response_text,
            )
            return

        self.terminate(
            reason=GECXTerminalReason.NORMAL_END,
            outcome=GECXTerminalOutcome.SESSION_END,
            source="ces_end_session",
            metadata={"end_session": metadata},
            response_text=response_text,
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
        normalized_output_encoding = (
            str(self.output_audio_encoding)
            .upper()
            .replace("AUDIO_ENCODING_", "")
            .replace("-", "_")
        )
        if (
            normalized_output_encoding not in {"MULAW", "ULAW", "LINEAR_16_MULAW"}
            or self.output_sample_rate_hertz != 8000
        ):
            raise ValueError(
                "GECX BYOVA CHUNK streaming currently requires "
                "output_audio_encoding=MULAW and output_sample_rate_hertz=8000"
            )
        self.suppress_long_leading_audio = bool(
            config.get("suppress_long_leading_audio", True)
        )
        self.output_leading_audio_min_ms = min(
            60000,
            max(1000, int(config.get("output_leading_audio_min_ms", 5000))),
        )
        self.output_speech_frame_ms = 20
        self.output_speech_rms_threshold = min(
            4000,
            max(1, int(config.get("output_speech_rms_threshold", 200))),
        )
        self.output_speech_start_frames = min(
            10,
            max(1, int(config.get("output_speech_start_frames", 2))),
        )
        self.output_speech_preroll_ms = min(
            1000,
            max(0, int(config.get("output_speech_preroll_ms", 100))),
        )
        self.output_speech_frame_bytes = (
            self.output_sample_rate_hertz * self.output_speech_frame_ms // 1000
        )
        self.output_speech_preroll_bytes = (
            self.output_sample_rate_hertz * self.output_speech_preroll_ms // 1000
        )
        self.output_leading_audio_min_bytes = (
            self.output_sample_rate_hertz * self.output_leading_audio_min_ms // 1000
        )
        self.output_audio_gate_tail_bytes = (
            self.output_speech_preroll_bytes
            + (self.output_speech_start_frames * self.output_speech_frame_bytes)
        )
        self.initial_message = config.get("initial_message", "Hello")
        self.enable_partial_responses = config.get("enable_partial_responses", True)
        self.force_input_format = config.get("force_input_format", "").lower()
        self.turn_response_timeout_seconds = float(
            config.get("turn_response_timeout_seconds", 30.0)
        )
        self.endpointing_silence_ms = min(
            5000, max(0, int(config.get("endpointing_silence_ms", 2000)))
        )
        self.input_preroll_ms = min(
            2000, max(0, int(config.get("input_preroll_ms", 500)))
        )
        self.input_pause_preroll_ms = min(
            1000, max(0, int(config.get("input_pause_preroll_ms", 250)))
        )
        self.terminal_response_grace_seconds = min(
            10.0,
            max(0.0, float(config.get("terminal_response_grace_seconds", 3.0))),
        )
        self.log_raw_terminal_metadata_debug = bool(
            config.get("log_raw_terminal_metadata_debug", False)
        )
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
        self.async_response_sinks: Dict[
            str, Callable[[Dict[str, Any]], bool]
        ] = {}
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

    def get_audio_delivery_mode(self) -> str:
        """GECX receives caller audio frames as they arrive from WxCC."""
        return "streaming"

    def should_cleanup_on_client_stream_end(self) -> bool:
        """Close CES after WxCC cancellation or request-stream failure."""
        return True

    def should_coalesce_speech_end_with_response(self) -> bool:
        """Keep END_OF_INPUT ordered ahead of the CES response stream."""
        return True

    def should_merge_speech_pauses(self) -> bool:
        """Keep a caller turn open briefly after gateway VAD reports silence."""
        return True

    def set_async_response_sink(
        self,
        conversation_id: str,
        response_sink: Callable[[Dict[str, Any]], bool],
    ) -> None:
        """Attach the active WxCC stream for autonomous CES output."""
        with self.sessions_lock:
            self.async_response_sinks[conversation_id] = response_sink
            stream_session = self.streaming_sessions.get(conversation_id)
        if stream_session is not None:
            stream_session.set_async_response_sink(response_sink)

    def clear_async_response_sink(
        self,
        conversation_id: str,
        response_sink: Callable[[Dict[str, Any]], bool],
    ) -> None:
        """Detach a completed WxCC stream without clearing a newer stream."""
        with self.sessions_lock:
            current_sink = self.async_response_sinks.get(conversation_id)
            if current_sink is response_sink:
                self.async_response_sinks.pop(conversation_id, None)
            stream_session = self.streaming_sessions.get(conversation_id)
        if stream_session is not None:
            stream_session.clear_async_response_sink(response_sink)

    def pause_speech_turn(self, conversation_id: str, silence_ms: int) -> None:
        """Hold a possible end and strip the silence that triggered gateway VAD."""
        with self.sessions_lock:
            stream_session = self.streaming_sessions.get(conversation_id)
        if stream_session and stream_session.pause_input_turn(silence_ms):
            self.logger.info(
                "[%s] [GECX] Holding speech end; removed %dms trailing silence",
                conversation_id,
                silence_ms,
            )

    def resume_speech_turn(self, conversation_id: str) -> None:
        """Resume the held caller turn with bounded speech-onset pre-roll."""
        with self.sessions_lock:
            stream_session = self.streaming_sessions.get(conversation_id)
        if stream_session and stream_session.resume_input_turn():
            self.logger.info(
                "[%s] [GECX] Merged resumed speech into the active caller turn",
                conversation_id,
            )

    def commit_speech_turn(self, conversation_id: str) -> None:
        """Flush a held caller turn before waiting for its CES response."""
        with self.sessions_lock:
            stream_session = self.streaming_sessions.get(conversation_id)
        if stream_session and stream_session.end_audio_turn():
            self.logger.info(
                "[%s] [GECX] Queued %dms endpointing silence after speech end",
                conversation_id,
                self.endpointing_silence_ms,
            )

    def handle_speech_boundary(
        self, conversation_id: str, message_data: Dict[str, Any]
    ) -> Generator[Dict[str, Any], None, None]:
        """Coordinate gateway speech boundaries with asynchronous CES output."""
        with self.sessions_lock:
            stream_session = self.streaming_sessions.get(conversation_id)

        if not stream_session:
            self.logger.warning(
                "[GECX] No active stream for speech boundary: %s", conversation_id
            )
            return

        if stream_session.is_terminal:
            yield from stream_session.drain_responses()
            return

        boundary_kind = message_data.get("speech_boundary", {}).get("kind")
        if boundary_kind == "speech_started":
            stream_session.begin_input_turn(expect_recognition=True)
            return

        if boundary_kind != "speech_ended":
            return

        if not message_data.get("speech_turn_committed"):
            self.commit_speech_turn(conversation_id)
        yield from stream_session.iter_turn_responses(
            timeout=self.turn_response_timeout_seconds,
            terminal_grace_seconds=self.terminal_response_grace_seconds,
        )

    @staticmethod
    def may_have_delayed_terminal(response_text: str) -> bool:
        """Return whether streamed announcement text likely precedes EndSession."""
        response_text = str(response_text or "").lower()
        terminal_cues = (
            "goodbye",
            "great day",
            "good day",
            "take care",
            "connect you",
            "transfer",
            "human agent",
            "live agent",
        )
        return any(cue in response_text for cue in terminal_cues)

    def get_available_agents(self) -> list:
        return self.agents

    def start_conversation(
        self, conversation_id: str, request_data: Dict[str, Any]
    ) -> Generator[Dict[str, Any], None, None]:
        self.logger.info(f"[GECX] Starting conversation: {conversation_id}")
        try:
            session_id = _make_ces_session_id()
            session_path = f"{self.app_path}/sessions/{session_id}"
            with self.sessions_lock:
                async_response_sink = self.async_response_sinks.get(
                    conversation_id
                )

            stream_session = GECXStreamingSession(
                connector=self,
                conversation_id=conversation_id,
                session_path=session_path,
                deployment_path=self.deployment_path,
                initial_message=self.initial_message,
                async_response_sink=async_response_sink,
            )
            stream_session.start()

            with self.sessions_lock:
                self.streaming_sessions[conversation_id] = stream_session
                latest_sink = self.async_response_sinks.get(conversation_id)

            if latest_sink is not None and latest_sink is not async_response_sink:
                stream_session.set_async_response_sink(latest_sink)

            yield from stream_session.iter_turn_responses(
                timeout=self.turn_response_timeout_seconds,
                terminal_grace_seconds=self.terminal_response_grace_seconds,
            )
        except Exception as exc:
            self.logger.error(
                f"[GECX] Error starting conversation {conversation_id}: {exc}",
                exc_info=True,
            )
            yield self.create_error_response(
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

        if stream_session.is_terminal:
            yield from stream_session.drain_responses()
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

        if not stream_session.enqueue_audio(audio_chunk):
            yield from stream_session.drain_responses()
            return

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
        if not stream_session.begin_input_turn():
            yield from stream_session.drain_responses()
            return
        if not stream_session.enqueue_text(text):
            yield from stream_session.drain_responses()
            return
        yield from stream_session.iter_turn_responses(
            timeout=self.turn_response_timeout_seconds,
            terminal_grace_seconds=self.terminal_response_grace_seconds,
        )

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
        if not stream_session.begin_input_turn():
            yield from stream_session.drain_responses()
            return
        if not stream_session.enqueue_event(event_name):
            yield from stream_session.drain_responses()
            return
        yield from stream_session.iter_turn_responses(
            timeout=self.turn_response_timeout_seconds,
            terminal_grace_seconds=self.terminal_response_grace_seconds,
        )

    def end_conversation(
        self, conversation_id: str, message_data: Optional[Dict[str, Any]] = None
    ) -> None:
        termination_reason = (message_data or {}).get(
            "termination_reason", "explicit_shutdown"
        )
        reason_map = {
            "client_cancelled": GECXTerminalReason.CLIENT_CANCELLED,
            "client_half_close": GECXTerminalReason.CLIENT_HALF_CLOSE,
            "stream_error": GECXTerminalReason.STREAM_ERROR,
        }
        terminal_reason = reason_map.get(
            termination_reason, GECXTerminalReason.EXPLICIT_SHUTDOWN
        )
        self.logger.info(
            "gecx_end_conversation conversation_id=%s reason=%s",
            conversation_id,
            termination_reason,
        )
        with self.sessions_lock:
            stream_session = self.streaming_sessions.pop(conversation_id, None)
            self.detected_formats.pop(conversation_id, None)
            self.async_response_sinks.pop(conversation_id, None)

        if stream_session:
            stream_session.stop(
                reason=terminal_reason,
                source=f"gateway_{termination_reason}",
            )

    def convert_wxcc_to_vendor(self, grpc_data: Any) -> Dict[str, Any]:
        return {"data": grpc_data, "converted_for": "gecx"}

    def convert_vendor_to_wxcc(self, vendor_data: Any) -> Any:
        return vendor_data

    # --- Audio helpers (adapted from Dialogflow CX connector) ---

    def input_audio_bytes_for_ms(self, duration_ms: int) -> int:
        """Return encoded input bytes representing the requested duration."""
        bytes_per_sample = (
            2
            if self._normalize_encoding_name(self.input_audio_encoding)
            == "LINEAR_16"
            else 1
        )
        return (
            self.input_sample_rate_hertz
            * max(0, duration_ms)
            * bytes_per_sample
            // 1000
        )

    def endpointing_silence_chunks(self) -> list[bytes]:
        """Build 100 ms silence chunks in the configured CES input codec."""
        remaining_ms = self.endpointing_silence_ms
        if remaining_ms <= 0:
            return []

        encoding = self._normalize_encoding_name(self.input_audio_encoding)
        if encoding == "LINEAR_16":
            silence_byte = b"\x00"
            bytes_per_sample = 2
        elif encoding == "ALAW":
            silence_byte = b"\xd5"
            bytes_per_sample = 1
        else:
            silence_byte = b"\xff"
            bytes_per_sample = 1

        chunks: list[bytes] = []
        while remaining_ms > 0:
            chunk_ms = min(100, remaining_ms)
            sample_count = self.input_sample_rate_hertz * chunk_ms // 1000
            chunks.append(silence_byte * sample_count * bytes_per_sample)
            remaining_ms -= chunk_ms
        return chunks

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
        audio_metadata = message_data.get("audio_metadata") or {}
        sample_rate_hertz = audio_metadata.get(
            "sample_rate_hertz", message_data.get("sample_rate_hertz")
        )
        encoding_value = audio_metadata.get(
            "encoding", message_data.get("encoding")
        )
        if sample_rate_hertz:
            rate = int(sample_rate_hertz)
            encoding = self._encoding_from_proto(encoding_value)
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
