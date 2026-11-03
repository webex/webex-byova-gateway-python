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
        expected_transport: str | None = None,
        expected_agent_id: str | None = None,
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
        self.expected_transport = expected_transport
        self.expected_agent_id = expected_agent_id
        self._baseline: set[str] | None = None
        self._baseline_conversation_ids: set[str] = set()
        self._conversation_id: str | None = None
        self._profile_verified = not (expected_transport or expected_agent_id)

    def begin(self) -> None:
        """Snapshot existing events before the browser dials."""
        events = self._fetch_events()
        self._baseline = {self._event_key(event) for event in events}
        self._baseline_conversation_ids = {
            str(event["conversation_id"])
            for event in events
            if event.get("conversation_id")
        }
        self._conversation_id = None
        self._profile_verified = not (self.expected_transport or self.expected_agent_id)

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
            self._verify_conversation_profile(new_events)
            terminal_event = self._terminal_event(new_events)
            if terminal_event is not None:
                if not self._profile_verified:
                    raise GatewayEventError(
                        "Gateway diagnostics did not prove the expected transport "
                        "and agent for the E2E conversation"
                    )
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
        if not self._profile_verified:
            raise GatewayEventError(
                "Gateway diagnostics did not prove the expected transport and agent "
                f"for conversation {self._conversation_id}"
            )
        if expected in {ExpectedOutcome.SESSION_END, ExpectedOutcome.TRANSFER}:
            raise GatewayEventError(
                "Gateway did not emit the expected terminal outcome "
                f"{expected.value} for conversation {self._conversation_id}"
            )
        return None

    def wait_for_conversation(self, timeout_seconds: float) -> dict[str, Any]:
        """Wait until one new conversation matches the configured gateway profile."""
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
            self._verify_conversation_profile(new_events)
            if self._conversation_id is not None and self._profile_verified:
                matching = [
                    event
                    for event in new_events
                    if event.get("conversation_id") == self._conversation_id
                    and self._matches_expected_profile(event)
                ]
                if matching:
                    return self._artifact_event(matching[0])

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
                "Gateway diagnostics did not expose the E2E conversation before "
                "caller input"
            )
        raise GatewayEventError(
            "Gateway diagnostics did not prove the expected transport and agent "
            f"for conversation {self._conversation_id} before caller input"
        )

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
        } - self._baseline_conversation_ids

        # When the test declares an expected transport or agent, prefer the one
        # conversation with explicit matching profile evidence. A bounded event
        # ring can expose the delayed terminal cleanup of an older call alongside
        # the call just placed by this run; that unrelated conversation must not
        # make otherwise exact correlation ambiguous.
        if self.expected_transport is not None or self.expected_agent_id is not None:
            matching_ids = {
                str(event["conversation_id"])
                for event in events
                if event.get("conversation_id")
                and str(event["conversation_id"]) not in self._baseline_conversation_ids
                and self._matches_expected_profile(event)
            }
            if len(matching_ids) > 1:
                raise GatewayEventError(
                    "Gateway diagnostics exposed multiple new conversations matching "
                    "the expected transport and agent during the E2E run"
                )
            if matching_ids:
                self._conversation_id = matching_ids.pop()
                return

        if len(conversation_ids) > 1:
            raise GatewayEventError(
                "Gateway diagnostics exposed multiple new conversations during the "
                "E2E run; use a dedicated entry point before asserting terminal events"
            )
        if conversation_ids:
            self._conversation_id = conversation_ids.pop()

    def _matches_expected_profile(self, event: dict[str, Any]) -> bool:
        """Return whether one event explicitly proves the configured profile."""
        if (
            self.expected_transport is not None
            and event.get("transport") != self.expected_transport
        ):
            return False
        if (
            self.expected_agent_id is not None
            and event.get("agent_id") != self.expected_agent_id
        ):
            return False
        return True

    def _verify_conversation_profile(self, events: list[dict[str, Any]]) -> None:
        """Require explicit transport/agent evidence for the bound conversation."""
        if self._conversation_id is None:
            return
        matching = [
            event
            for event in events
            if event.get("conversation_id") == self._conversation_id
        ]
        for event in matching:
            transport = event.get("transport")
            agent_id = event.get("agent_id")
            if (
                self.expected_transport is not None
                and transport is not None
                and transport != self.expected_transport
            ):
                raise GatewayEventError(
                    "Gateway transport mismatch: expected "
                    f"{self.expected_transport}, observed {transport}"
                )
            if (
                self.expected_agent_id is not None
                and agent_id is not None
                and agent_id != self.expected_agent_id
            ):
                raise GatewayEventError(
                    "Gateway agent mismatch: expected "
                    f"{self.expected_agent_id}, observed {agent_id}"
                )
            transport_matches = (
                self.expected_transport is None or transport == self.expected_transport
            )
            agent_matches = (
                self.expected_agent_id is None or agent_id == self.expected_agent_id
            )
            if transport_matches and agent_matches:
                self._profile_verified = True

    def _terminal_event(self, events: list[dict[str, Any]]) -> dict[str, Any] | None:
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
        self._assert_event_profile(event)
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

    def _assert_event_profile(self, event: dict[str, Any]) -> None:
        """Tie terminal evidence to the configured transport and agent."""
        if (
            self.expected_transport is not None
            and event.get("transport") != self.expected_transport
        ):
            raise GatewayEventError(
                "Gateway terminal transport mismatch: expected "
                f"{self.expected_transport}, observed {event.get('transport')}"
            )
        if (
            self.expected_agent_id is not None
            and event.get("agent_id") != self.expected_agent_id
        ):
            raise GatewayEventError(
                "Gateway terminal agent mismatch: expected "
                f"{self.expected_agent_id}, observed {event.get('agent_id')}"
            )

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
                "transport",
            )
            if key in event
        }
