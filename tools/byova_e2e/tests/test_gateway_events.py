import pytest
from byova_e2e.gateway_events import GatewayEventError, GatewayEventObserver
from byova_e2e.models import ExpectedOutcome


class _Snapshots:
    def __init__(self, *snapshots: list[dict[str, object]]) -> None:
        self.snapshots = list(snapshots)

    def __call__(self) -> list[dict[str, object]]:
        if len(self.snapshots) > 1:
            return self.snapshots.pop(0)
        return self.snapshots[0]


def _start() -> dict[str, object]:
    return {
        "event_type": "start",
        "conversation_id": "conversation-1",
        "agent_id": "GECX Agent",
        "timestamp": 10.0,
    }


def _terminal(outcome: str) -> dict[str, object]:
    return {
        "event_type": "terminal",
        "conversation_id": "conversation-1",
        "agent_id": "GECX Agent",
        "timestamp": 12.0,
        "outcome": outcome,
        "name": "transfer_requested",
        "metadata": {"must_not": "reach the artifact"},
    }


def _message(timestamp: float = 11.0) -> dict[str, object]:
    return {
        "event_type": "message",
        "conversation_id": "conversation-1",
        "agent_id": "GECX Agent",
        "timestamp": timestamp,
    }


def test_normal_response_rejects_unexpected_gateway_terminal_event() -> None:
    snapshots = _Snapshots([], [_start(), _terminal("TRANSFER_TO_AGENT")])
    observer = GatewayEventObserver(
        "http://127.0.0.1:8080",
        poll_interval_seconds=0,
        fetch_events=snapshots,
    )
    observer.begin()

    with pytest.raises(
        GatewayEventError,
        match="unexpected terminal outcome TRANSFER_TO_AGENT",
    ):
        observer.assert_outcome(ExpectedOutcome.RESPONSE, 0)


def test_transfer_is_proven_by_exact_gateway_terminal_event() -> None:
    terminal = _terminal("TRANSFER_TO_AGENT")
    snapshots = _Snapshots([], [_start(), terminal])
    observer = GatewayEventObserver(
        "http://127.0.0.1:8080/api/connections",
        poll_interval_seconds=0,
        fetch_events=snapshots,
    )
    observer.begin()

    event = observer.assert_outcome(ExpectedOutcome.TRANSFER, 0)

    assert event == {
        "event_type": "terminal",
        "conversation_id": "conversation-1",
        "agent_id": "GECX Agent",
        "timestamp": 12.0,
        "outcome": "TRANSFER_TO_AGENT",
        "name": "transfer_requested",
    }
    assert observer.endpoint == "http://127.0.0.1:8080/api/connections"


def test_session_end_rejects_transfer_gateway_outcome() -> None:
    snapshots = _Snapshots([], [_start(), _terminal("TRANSFER_TO_AGENT")])
    observer = GatewayEventObserver(
        "http://127.0.0.1:8080",
        poll_interval_seconds=0,
        fetch_events=snapshots,
    )
    observer.begin()

    with pytest.raises(
        GatewayEventError,
        match="expected session-end, observed TRANSFER_TO_AGENT",
    ):
        observer.assert_outcome(ExpectedOutcome.SESSION_END, 0)


def test_session_end_is_proven_by_exact_gateway_terminal_event() -> None:
    terminal = {
        **_terminal("SESSION_END"),
        "name": "session_ended",
    }
    snapshots = _Snapshots([], [_start(), terminal])
    observer = GatewayEventObserver(
        "http://127.0.0.1:8080",
        poll_interval_seconds=0,
        fetch_events=snapshots,
    )
    observer.begin()

    event = observer.assert_outcome(ExpectedOutcome.SESSION_END, 0)

    assert event is not None
    assert event["outcome"] == "SESSION_END"
    assert event["name"] == "session_ended"


def test_terminal_assertion_requires_one_new_gateway_conversation() -> None:
    second_start = {**_start(), "conversation_id": "conversation-2"}
    snapshots = _Snapshots([], [_start(), second_start])
    observer = GatewayEventObserver(
        "http://127.0.0.1:8080",
        poll_interval_seconds=0,
        fetch_events=snapshots,
    )
    observer.begin()

    with pytest.raises(GatewayEventError, match="multiple new conversations"):
        observer.assert_outcome(ExpectedOutcome.RESPONSE, 0)


def test_normal_response_without_terminal_event_is_proven() -> None:
    snapshots = _Snapshots([], [_start()])
    observer = GatewayEventObserver(
        "http://127.0.0.1:8080",
        poll_interval_seconds=0,
        fetch_events=snapshots,
    )
    observer.begin()

    assert observer.assert_outcome(ExpectedOutcome.RESPONSE, 0) is None


def test_normal_response_binds_after_start_event_is_evicted() -> None:
    snapshots = _Snapshots([], [_message()])
    observer = GatewayEventObserver(
        "http://127.0.0.1:8080",
        poll_interval_seconds=0,
        fetch_events=snapshots,
    )
    observer.begin()

    assert observer.assert_outcome(ExpectedOutcome.RESPONSE, 0) is None
