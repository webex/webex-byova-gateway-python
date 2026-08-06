"""Correlate live E2E calls with gateway diagnostic events."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import requests

from .models import ExpectedOutcome

_GATEWAY_OUTCOMES = {
    "SESSION_END": ExpectedOutcome.SESSION_END,
    "TRANSFER_TO_AGENT": ExpectedOutcome.TRANSFER,
}


class GatewayEventError(RuntimeError):
    """Gateway event evidence could not prove the expected call outcome."""


class GatewayEventObserver:
    """Observe one new gateway conversation through ``/api/connections``."""

    def __init__(
        self,
        endpoint: str,
        *,
        poll_interval_seconds: float = 0.2,
        request_timeout_seconds: float = 5.0,
        fetch_events: Callable[[], list[dict[str, Any]]] | None = None,
    ) -> None:
        endpoint = endpoint.rstrip("/")
        self.endpoint = (
            endpoint
            if endpoint.endswith("/api/connections")
            else f"{endpoint}/api/connections"
        )
        self.poll_interval_seconds = max(0.0, poll_interval_seconds)
        self.request_timeout_seconds = request_timeout_seconds
        self._fetch_events_override = fetch_events
        self._baseline: set[str] | None = None
        self._conversation_id: str | None = None

    def begin(self) -> None:
        """Snapshot existing events before the browser dials."""
        self._baseline = {self._event_key(event) for event in self._fetch_events()}
        self._conversation_id = None

    def assert_outcome(
        self,
        expected: ExpectedOutcome,
        timeout_seconds: float,
    ) -> dict[str, Any] | None:
        """Assert the terminal event for the single conversation started by this run."""
        if expected == ExpectedOutcome.RESPONSE_START:
            raise GatewayEventError(
                "A response-start expectation cannot prove a terminal outcome"
            )
        if self._baseline is None:
            raise GatewayEventError("Gateway event observation was not started")

        deadline = time.monotonic() + max(0.0, timeout_seconds)
        while True:
            new_events = [
                event
                for event in self._fetch_events()
                if self._event_key(event) not in self._baseline
            ]
            self._bind_conversation(new_events)
            terminal_event = self._terminal_event(new_events)
            if terminal_event is not None:
                return self._assert_terminal_outcome(expected, terminal_event)

            if time.monotonic() >= deadline:
                break
            time.sleep(
                min(
                    self.poll_interval_seconds,
                    max(0.0, deadline - time.monotonic()),
                )
            )

        if self._conversation_id is None:
            raise GatewayEventError(
                "Gateway diagnostics did not expose the E2E conversation"
            )
        if expected in {ExpectedOutcome.SESSION_END, ExpectedOutcome.TRANSFER}:
            raise GatewayEventError(
                "Gateway did not emit the expected terminal outcome "
                f"{expected.value} for conversation {self._conversation_id}"
            )
        return None

    def _bind_conversation(self, events: list[dict[str, Any]]) -> None:
        if self._conversation_id is not None:
            return
        # The monitoring endpoint is a bounded event ring. Long streamed prompts can
        # evict the initial ``start`` event before the expectation is evaluated, so
        # correlate from every unique new event rather than requiring that one event.
        conversation_ids = {
            str(event["conversation_id"])
            for event in events
            if event.get("conversation_id")
        }
        if len(conversation_ids) > 1:
            raise GatewayEventError(
                "Gateway diagnostics exposed multiple new conversations during the "
                "E2E run; use a dedicated entry point before asserting terminal events"
            )
        if conversation_ids:
            self._conversation_id = conversation_ids.pop()

    def _terminal_event(
        self, events: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        if self._conversation_id is None:
            return None
        terminal_events = [
            event
            for event in events
            if event.get("event_type") == "terminal"
            and event.get("conversation_id") == self._conversation_id
        ]
        if len(terminal_events) > 1:
            outcomes = ", ".join(
                str(event.get("outcome", "unknown")) for event in terminal_events
            )
            raise GatewayEventError(
                "Gateway emitted multiple terminal events for conversation "
                f"{self._conversation_id}: {outcomes}"
            )
        return terminal_events[0] if terminal_events else None

    def _assert_terminal_outcome(
        self,
        expected: ExpectedOutcome,
        event: dict[str, Any],
    ) -> dict[str, Any]:
        outcome = str(event.get("outcome", ""))
        if expected == ExpectedOutcome.RESPONSE:
            raise GatewayEventError(
                f"Gateway emitted unexpected terminal outcome {outcome} "
                "for a normal response"
            )
        if _GATEWAY_OUTCOMES.get(outcome) != expected:
            raise GatewayEventError(
                "Gateway terminal outcome mismatch: expected "
                f"{expected.value}, observed {outcome}"
            )
        return self._artifact_event(event)

    def _fetch_events(self) -> list[dict[str, Any]]:
        events: Any
        if self._fetch_events_override is not None:
            events = self._fetch_events_override()
        else:
            try:
                response = requests.get(
                    self.endpoint,
                    timeout=self.request_timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as error:
                raise GatewayEventError(
                    f"Unable to read gateway events from {self.endpoint}: {error}"
                ) from error
            events = (
                payload.get("connection_events") if isinstance(payload, dict) else None
            )
        if not isinstance(events, list) or not all(
            isinstance(event, dict) for event in events
        ):
            raise GatewayEventError(
                "Gateway event endpoint returned an invalid connection_events list"
            )
        return events

    @staticmethod
    def _event_key(event: dict[str, Any]) -> str:
        return json.dumps(event, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _artifact_event(event: dict[str, Any]) -> dict[str, Any]:
        """Retain correlation fields without copying arbitrary event metadata."""
        return {
            key: event[key]
            for key in (
                "event_type",
                "conversation_id",
                "agent_id",
                "timestamp",
                "outcome",
                "name",
            )
            if key in event
        }
