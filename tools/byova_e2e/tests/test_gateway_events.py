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


def test_wait_for_conversation_returns_matching_profile_evidence() -> None:
    start = {
        **_start(),
        "transport": "websocket",
        "agent_id": "Local Audio: Local Playback",
    }
    observer = GatewayEventObserver(
        "http://127.0.0.1:8080",
        poll_interval_seconds=0,
        fetch_events=_Snapshots([], [start]),
        expected_transport="websocket",
        expected_agent_id="Local Audio: Local Playback",
    )
    observer.begin()

    event = observer.wait_for_conversation(0)

    assert event == {
        "event_type": "start",
        "conversation_id": "conversation-1",
        "agent_id": "Local Audio: Local Playback",
        "timestamp": 10.0,
        "transport": "websocket",
    }


def test_wait_for_conversation_requires_new_gateway_conversation() -> None:
    observer = GatewayEventObserver(
        "http://127.0.0.1:8080",
        poll_interval_seconds=0,
        fetch_events=_Snapshots([], []),
    )
    observer.begin()

    with pytest.raises(
        GatewayEventError,
        match="did not expose the E2E conversation before caller input",
    ):
        observer.wait_for_conversation(0)


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


def test_expected_profile_ignores_unrelated_delayed_conversation() -> None:
    unrelated_start = {
        **_start(),
        "conversation_id": "old-conversation",
        "transport": "websocket",
        "agent_id": "Local Audio: Local Playback",
    }
    unrelated_terminal = {
        **_terminal("SESSION_END"),
        "conversation_id": "old-conversation",
        "transport": "websocket",
        "agent_id": "Local Audio: Local Playback",
    }
    expected_start = {
        **_start(),
        "transport": "websocket",
        "agent_id": "Local Audio: Local Playback",
    }
    expected_terminal = {
        **_terminal("TRANSFER_TO_AGENT"),
        "transport": "websocket",
        "agent_id": "Local Audio: Local Playback",
    }
    observer = GatewayEventObserver(
        "http://127.0.0.1:8080",
        poll_interval_seconds=0,
        fetch_events=_Snapshots(
            [unrelated_start],
            [
                unrelated_start,
                unrelated_terminal,
                expected_start,
                expected_terminal,
            ],
        ),
        expected_transport="websocket",
        expected_agent_id="Local Audio: Local Playback",
    )
    observer.begin()

    event = observer.assert_outcome(ExpectedOutcome.TRANSFER, 0)

    assert event is not None
    assert event["conversation_id"] == "conversation-1"


def test_expected_profile_rejects_multiple_matching_conversations() -> None:
    first = {
        **_start(),
        "transport": "websocket",
        "agent_id": "Local Audio: Local Playback",
    }
    second = {
        **first,
        "conversation_id": "conversation-2",
    }
    observer = GatewayEventObserver(
        "http://127.0.0.1:8080",
        poll_interval_seconds=0,
        fetch_events=_Snapshots([], [first, second]),
        expected_transport="websocket",
        expected_agent_id="Local Audio: Local Playback",
    )
    observer.begin()

    with pytest.raises(GatewayEventError, match="multiple new conversations matching"):
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


def test_terminal_outcome_requires_expected_websocket_local_audio_profile() -> None:
    start = {
        **_start(),
        "agent_id": "Local Audio: Local Playback",
        "transport": "websocket",
    }
    terminal = {
        **_terminal("TRANSFER_TO_AGENT"),
        "agent_id": "Local Audio: Local Playback",
        "transport": "websocket",
    }
    observer = GatewayEventObserver(
        "http://127.0.0.1:8080",
        poll_interval_seconds=0,
        fetch_events=_Snapshots([], [start, terminal]),
        expected_transport="websocket",
        expected_agent_id="Local Audio: Local Playback",
    )
    observer.begin()

    event = observer.assert_outcome(ExpectedOutcome.TRANSFER, 0)

    assert event is not None
    assert event["transport"] == "websocket"
    assert event["agent_id"] == "Local Audio: Local Playback"


def test_gateway_profile_rejects_wrong_transport() -> None:
    observer = GatewayEventObserver(
        "http://127.0.0.1:8080",
        poll_interval_seconds=0,
        fetch_events=_Snapshots([], [{**_start(), "transport": "grpc"}]),
        expected_transport="websocket",
    )
    observer.begin()

    with pytest.raises(GatewayEventError, match="transport mismatch"):
        observer.assert_outcome(ExpectedOutcome.RESPONSE, 0)


def test_terminal_profile_cannot_differ_from_matching_start_event() -> None:
    start = {
        **_start(),
        "agent_id": "Local Audio: Local Playback",
        "transport": "websocket",
    }
    terminal = {
        **_terminal("TRANSFER_TO_AGENT"),
        "agent_id": "Other Agent",
        "transport": "websocket",
    }
    observer = GatewayEventObserver(
        "http://127.0.0.1:8080",
        poll_interval_seconds=0,
        fetch_events=_Snapshots([], [start, terminal]),
        expected_transport="websocket",
        expected_agent_id="Local Audio: Local Playback",
    )
    observer.begin()

    with pytest.raises(GatewayEventError, match="agent mismatch"):
        observer.assert_outcome(ExpectedOutcome.TRANSFER, 0)
