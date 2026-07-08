"""
Tests for the GECX (CX Agent Studio / CES) connector.
"""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.connectors.gecx_connector import (
    GECXConnector,
    GECXStreamingSession,
    _make_ces_session_id,
    _ces_audio_encoding,
)


@pytest.fixture
def gecx_config():
    return {
        "project_id": "test-project",
        "location": "us",
        "application_id": "test-app",
        "deployment_id": "test-deployment",
        "agents": ["Test GECX Agent"],
        "input_sample_rate_hertz": 8000,
        "output_sample_rate_hertz": 8000,
        "input_audio_encoding": "MULAW",
        "output_audio_encoding": "MULAW",
        "initial_message": "Hello",
    }


@pytest.fixture
def connector(gecx_config):
    with patch("src.connectors.gecx_connector.ces_v1.SessionServiceClient") as mock_client:
        instance = MagicMock()
        mock_client.return_value = instance
        conn = GECXConnector(gecx_config)
        conn.session_client = instance
        yield conn


class TestSessionId:
    def test_make_ces_session_id_matches_pattern(self):
        session_id = _make_ces_session_id()
        assert re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-_]{4,62}$", session_id)


class TestGECXConnectorInit:
    def test_builds_deployment_path_from_parts(self, gecx_config):
        with patch("src.connectors.gecx_connector.ces_v1.SessionServiceClient"):
            connector = GECXConnector(gecx_config)
        assert connector.deployment_path == (
            "projects/test-project/locations/us/apps/test-app/deployments/test-deployment"
        )

    def test_accepts_full_deployment_path(self):
        config = {
            "deployment": (
                "projects/p/locations/us/apps/a/deployments/d"
            ),
            "agents": ["Agent"],
        }
        with patch("src.connectors.gecx_connector.ces_v1.SessionServiceClient"):
            connector = GECXConnector(config)
        assert connector.deployment_path.endswith("/deployments/d")
        assert connector.application_id == "a"


class TestRequestGenerator:
    def test_first_message_is_session_config(self, connector):
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
            initial_message=None,
        )

        generator = session._request_generator()
        first = next(generator)

        assert first.config.session.endswith("/sessions/s1")
        assert first.config.deployment == connector.deployment_path
        assert first.config.input_audio_config.sample_rate_hertz == 8000

    def test_initial_text_follows_config_message(self, connector):
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
            initial_message="Hello",
        )

        generator = session._request_generator()
        next(generator)  # config
        second = next(generator)

        assert second.realtime_input.text == "Hello"


class TestServerMessageMapping:
    def test_session_output_maps_to_connector_responses(self, connector):
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
        )

        message = SimpleNamespace(
            recognition_result=None,
            interruption_signal=None,
            end_session=None,
            go_away=None,
            session_output=SimpleNamespace(
                text="Hi there",
                audio=b"\x01\x02",
                turn_completed=True,
                end_session=False,
            ),
        )

        session._handle_server_message(message)
        responses = session.drain_responses()

        assert len(responses) == 2
        assert responses[0]["message_type"] == "agent_response"
        assert responses[0]["text"] == "Hi there"
        assert responses[0]["response_type"] == "final"
        assert responses[1]["message_type"] == "audio"
        # Audio is buffered per turn and wrapped in a WxCC WAV container.
        assert responses[1]["audio_content"].startswith(b"RIFF")
        assert responses[1]["audio_content"].endswith(b"\x01\x02")

    def test_end_session_emits_session_end_event(self, connector):
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
        )

        message = SimpleNamespace(
            recognition_result=None,
            interruption_signal=None,
            session_output=None,
            go_away=None,
            end_session=SimpleNamespace(metadata={}),
        )

        session._handle_server_message(message)
        responses = session.drain_responses()

        assert responses[0]["message_type"] == "session_end"
        assert responses[0]["output_events"][0]["event_type"] == "SESSION_END"

    def _end_session(self, connector, metadata):
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
        )
        message = SimpleNamespace(
            recognition_result=None,
            interruption_signal=None,
            session_output=None,
            go_away=None,
            end_session=SimpleNamespace(metadata=metadata),
        )
        session._handle_server_message(message)
        return session.drain_responses()

    def test_end_session_with_transfer_flag_emits_transfer(self, connector):
        responses = self._end_session(
            connector, {"transfer": True, "reason": "caller asked for a human"}
        )
        assert responses[0]["message_type"] == "transfer"
        assert responses[0]["output_events"][0]["event_type"] == "TRANSFER_TO_HUMAN"
        assert responses[0]["output_events"][0]["metadata"]["reason"] == (
            "caller asked for a human"
        )

    def test_end_session_with_reason_keyword_emits_transfer(self, connector):
        responses = self._end_session(
            connector, {"reason": "agent_requested_handoff"}
        )
        assert responses[0]["message_type"] == "transfer"

    def test_end_session_with_string_flag_emits_transfer(self, connector):
        responses = self._end_session(connector, {"escalate": "true"})
        assert responses[0]["message_type"] == "transfer"

    def test_end_session_with_session_escalated_flag_emits_transfer(self, connector):
        # This is the exact payload GECX emits on escalation.
        responses = self._end_session(connector, {"session_escalated": True})
        assert responses[0]["message_type"] == "transfer"

    def test_end_session_with_escalation_key_name_emits_transfer(self, connector):
        # Key-name keyword match catches naming variants generically.
        responses = self._end_session(connector, {"agent_escalated_call": True})
        assert responses[0]["message_type"] == "transfer"

    def test_end_session_normal_completion_is_not_transfer(self, connector):
        responses = self._end_session(connector, {"reason": "user said goodbye"})
        assert responses[0]["message_type"] == "session_end"

    def test_end_session_half_closes_stream(self, connector):
        """CES aborts with CLIENT_HALF_CLOSE_TIMEOUT unless we stop sending
        after an EndSession; the session must signal the request generator to
        return (stop event set + STREAM_STOP sentinel enqueued)."""
        from src.connectors import gecx_connector as gecx_mod

        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
        )
        message = SimpleNamespace(
            recognition_result=None,
            interruption_signal=None,
            session_output=None,
            go_away=None,
            end_session=SimpleNamespace(metadata={"transfer": True}),
        )
        assert not session._stop_event.is_set()
        session._handle_server_message(message)
        assert session._stop_event.is_set()
        assert session.inbound_queue.get_nowait() is gecx_mod._STREAM_STOP


class TestAudioFormat:
    def test_resolve_input_format_from_gateway_metadata(self, connector):
        rate, encoding = connector._resolve_input_format(
            b"\x00" * 640,
            {"sample_rate_hertz": 8000, "encoding": 2},
            "conv-1",
        )
        assert rate == 8000
        assert encoding == "MULAW"

    def test_ces_audio_encoding_mulaw(self):
        with patch("src.connectors.gecx_connector.ces_v1") as mock_ces:
            mock_ces.AudioEncoding.MULAW = 2
            assert _ces_audio_encoding("MULAW") == 2


class TestSendMessage:
    def test_send_message_enqueues_audio_and_drains_responses(self, connector):
        stream_session = MagicMock()
        stream_session.drain_responses.return_value = [
            connector.create_response(
                conversation_id="conv-1",
                message_type="agent_response",
                text="OK",
                response_type="final",
            )
        ]

        with patch.object(connector, "streaming_sessions", {"conv-1": stream_session}):
            responses = list(
                connector.send_message(
                    "conv-1",
                    {"input_type": "audio", "audio_data": b"\xff" * 640},
                )
            )

        stream_session.enqueue_audio.assert_called_once()
        assert responses[0]["text"] == "OK"
