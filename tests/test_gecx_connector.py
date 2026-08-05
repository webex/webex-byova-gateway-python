"""
Tests for the GECX (CX Agent Studio / CES) connector.
"""

from __future__ import annotations

import logging
import re
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.connectors.gecx_connector import (
    _AUDIO_END,
    _STREAM_STOP,
    GECXConnector,
    GECXStreamingSession,
    GECXTerminalOutcome,
    GECXTerminalReason,
    _ces_audio_encoding,
    _make_ces_session_id,
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

    def test_default_endpointing_silence_has_margin_above_one_second(
        self, gecx_config
    ):
        with patch("src.connectors.gecx_connector.ces_v1.SessionServiceClient"):
            connector = GECXConnector(gecx_config)

        assert connector.endpointing_silence_ms == 2000

    def test_barge_in_is_disabled_by_default(self, gecx_config):
        with patch("src.connectors.gecx_connector.ces_v1.SessionServiceClient"):
            connector = GECXConnector(gecx_config)

        assert connector.barge_in_enabled is False

    def test_barge_in_can_be_enabled_explicitly(self, gecx_config):
        gecx_config["barge_in_enabled"] = True

        with patch("src.connectors.gecx_connector.ces_v1.SessionServiceClient"):
            connector = GECXConnector(gecx_config)

        assert connector.barge_in_enabled is True

    @pytest.mark.parametrize(
        ("encoding", "sample_rate"),
        [("LINEAR16", 8000), ("MULAW", 16000)],
    )
    def test_rejects_output_format_that_wxcc_chunk_stream_cannot_play(
        self, gecx_config, encoding, sample_rate
    ):
        gecx_config["output_audio_encoding"] = encoding
        gecx_config["output_sample_rate_hertz"] = sample_rate

        with patch("src.connectors.gecx_connector.ces_v1.SessionServiceClient"):
            with pytest.raises(
                ValueError,
                match="CHUNK streaming currently requires",
            ):
                GECXConnector(gecx_config)


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

    def test_no_caller_audio_is_yielded_after_terminal_decision(self, connector):
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
            initial_message=None,
        )
        session.enqueue_audio(b"caller audio")
        session.terminate(
            GECXTerminalReason.NORMAL_END,
            GECXTerminalOutcome.SESSION_END,
            "test",
        )

        generator = session._request_generator()
        next(generator)  # Session config is always the first CES message.
        with pytest.raises(StopIteration):
            next(generator)

    def test_audio_end_yields_codec_silence_for_ces_endpointing(self, connector):
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
            initial_message=None,
        )
        session.inbound_queue.put(_AUDIO_END)
        session.inbound_queue.put(_STREAM_STOP)

        generator = session._request_generator()
        next(generator)  # config
        endpointing_messages = list(generator)

        assert len(endpointing_messages) == 20
        assert all(
            message.realtime_input.audio == b"\xff" * 800
            for message in endpointing_messages
        )

    def test_gateway_vad_flushes_one_intact_buffered_audio_turn(self, connector):
        connector.input_preroll_ms = 1
        connector.endpointing_silence_ms = 100
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
            initial_message=None,
        )

        session.enqueue_audio(b"0123456789")
        session.begin_input_turn()
        session.enqueue_audio(b"ABCD")
        session.end_audio_turn()
        session.inbound_queue.put(_STREAM_STOP)

        generator = session._request_generator()
        next(generator)  # config
        audio_messages = [
            message.realtime_input.audio for message in generator
        ]

        assert audio_messages == [b"23456789ABCD", b"\xff" * 800]

    def test_gateway_vad_compacts_pause_and_merges_resume_preroll(
        self, connector
    ):
        connector.input_preroll_ms = 1
        connector.input_pause_preroll_ms = 1
        connector.endpointing_silence_ms = 100
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
            initial_message=None,
        )

        session.enqueue_audio(b"0123456789")
        session.begin_input_turn()
        session.enqueue_audio(b"abcdefgh")
        assert session.pause_input_turn(silence_ms=1) is True
        session.enqueue_audio(b"ABCDEFGHIJKL")
        assert session.resume_input_turn() is True
        session.end_audio_turn()
        session.inbound_queue.put(_STREAM_STOP)

        generator = session._request_generator()
        next(generator)  # config
        audio_messages = [
            message.realtime_input.audio for message in generator
        ]

        assert audio_messages == [b"23456789EFGHIJKL", b"\xff" * 800]

    def test_committed_pause_preserves_resumed_onset_for_next_turn(
        self, connector
    ):
        connector.input_preroll_ms = 1
        connector.input_pause_preroll_ms = 1
        connector.endpointing_silence_ms = 1
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
            initial_message=None,
        )

        session.enqueue_audio(b"0123456789")
        session.begin_input_turn()
        session.enqueue_audio(b"abcdefgh")
        assert session.pause_input_turn(silence_ms=1) is True
        session.enqueue_audio(b"ABCDEFGHIJKL")
        assert session.end_audio_turn() is True
        session.begin_input_turn()
        session.enqueue_audio(b"mnopqrst")
        assert session.end_audio_turn() is True
        session.inbound_queue.put(_STREAM_STOP)

        generator = session._request_generator()
        next(generator)  # config
        audio_messages = [
            message.realtime_input.audio for message in generator
        ]

        assert audio_messages == [
            b"23456789",
            b"\xff" * 8,
            b"EFGHIJKLmnopqrst",
            b"\xff" * 8,
        ]


class TestServerMessageMapping:
    @staticmethod
    def _server_output(
        audio: bytes,
        *,
        text: str = "",
        turn_completed: bool = False,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            recognition_result=None,
            interruption_signal=None,
            end_session=None,
            go_away=None,
            session_output=SimpleNamespace(
                text=text,
                audio=audio,
                turn_completed=turn_completed,
                end_session=False,
            ),
        )

    def test_session_output_streams_raw_chunk_then_one_final(self, connector):
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

        session.begin_input_turn()
        session._handle_server_message(message)
        responses = list(session.iter_turn_responses(timeout=0.1))

        assert session._turn_completed.is_set()
        assert len(responses) == 2
        assert responses[0]["message_type"] == "audio"
        assert responses[0]["text"] == ""
        assert responses[0]["response_type"] == "chunk"
        assert responses[0]["audio_content"] == b"\x01\x02"
        assert responses[1]["message_type"] == "silence"
        assert responses[1]["response_type"] == "final"
        assert responses[1]["audio_content"] == b""

    def test_first_audio_chunk_is_available_before_ces_turn_completion(
        self, connector
    ):
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
        )
        session.begin_input_turn()
        stream = session.iter_turn_responses(timeout=1.0)

        session._handle_server_message(
            SimpleNamespace(
                recognition_result=None,
                interruption_signal=None,
                end_session=None,
                go_away=None,
                session_output=SimpleNamespace(
                    text="",
                    audio=b"first frame",
                    turn_completed=False,
                    end_session=False,
                ),
            )
        )

        assert session._turn_completed.is_set() is False
        first_response = next(stream)
        assert first_response["response_type"] == "chunk"
        assert first_response["audio_content"] == b"first frame"

        session._handle_server_message(
            SimpleNamespace(
                recognition_result=None,
                interruption_signal=None,
                end_session=None,
                go_away=None,
                session_output=SimpleNamespace(
                    text="",
                    audio=b"",
                    turn_completed=True,
                    end_session=False,
                ),
            )
        )
        remaining = list(stream)

        assert [response["response_type"] for response in remaining] == ["final"]

    def test_autonomous_output_pushes_to_live_sink_without_barge_in_by_default(
        self, connector
    ):
        delivered = []

        def response_sink(response):
            delivered.append(response)
            return True

        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-autonomous-no-barge-in",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
            async_response_sink=response_sink,
        )

        session._handle_server_message(
            self._server_output(b"no-input prompt audio")
        )

        assert len(delivered) == 1
        assert delivered[0]["barge_in_enabled"] is False

    def test_autonomous_output_pushes_to_live_sink_with_barge_in_when_enabled(
        self, connector
    ):
        connector.barge_in_enabled = True
        delivered = []

        def response_sink(response):
            delivered.append(response)
            return True

        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-autonomous",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
            async_response_sink=response_sink,
        )

        session._handle_server_message(
            self._server_output(
                b"no-input prompt audio",
                text="I'm still here.",
            )
        )

        assert session.drain_responses() == []
        assert len(delivered) == 1
        assert delivered[0]["response_type"] == "chunk"
        assert delivered[0]["audio_content"] == b"no-input prompt audio"
        assert delivered[0]["barge_in_enabled"] is True

        session._handle_server_message(
            self._server_output(b"", turn_completed=True)
        )

        assert [response["response_type"] for response in delivered] == [
            "chunk",
            "final",
        ]

    def test_caller_owned_output_stays_on_ordered_pull_path(self, connector):
        delivered = []
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-caller-owned",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
            async_response_sink=lambda response: not delivered.append(response),
        )

        session.begin_input_turn()
        session._handle_server_message(
            self._server_output(
                b"caller reply audio",
                text="Here is your answer.",
                turn_completed=True,
            )
        )

        assert delivered == []
        responses = list(session.iter_turn_responses(timeout=0.1))
        assert [response["response_type"] for response in responses] == [
            "chunk",
            "final",
        ]
        assert responses[0]["barge_in_enabled"] is False

    def test_caller_turn_suppresses_stale_no_input_prompt_until_ces_ack(
        self, connector
    ):
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-caller-reply",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
        )

        session.begin_input_turn(expect_recognition=True)
        session._handle_server_message(
            self._server_output(
                b"stale no-input audio",
                text="I did not catch that.",
                turn_completed=False,
            )
        )
        session.end_audio_turn()
        session._handle_server_message(
            SimpleNamespace(
                recognition_result=None,
                interruption_signal=SimpleNamespace(),
                end_session=None,
                go_away=None,
                session_output=None,
            )
        )
        session._handle_server_message(
            self._server_output(b"", turn_completed=True)
        )

        assert session.drain_responses() == []
        assert session._turn_completed.is_set() is False

        session._handle_server_message(
            SimpleNamespace(
                recognition_result=SimpleNamespace(
                    transcript="My name is Adam and my store number is 1234"
                ),
                interruption_signal=None,
                end_session=None,
                go_away=None,
                session_output=None,
            )
        )
        session._handle_server_message(
            self._server_output(
                b"correct reply audio",
                text="Great, Adam. What can I help you with today?",
                turn_completed=True,
            )
        )

        responses = list(session.iter_turn_responses(timeout=0.1))

        assert [response["response_type"] for response in responses] == [
            "chunk",
            "final",
        ]
        assert responses[0]["audio_content"] == b"correct reply audio"
        assert responses[1]["message_type"] == "silence"

    def test_suppresses_anomalous_low_energy_lead_until_speech(self, connector):
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-leading-audio",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
        )
        long_low_energy_frame = b"\xfb" * (connector.output_sample_rate_hertz * 6)

        session._handle_server_message(
            self._server_output(long_low_energy_frame)
        )

        assert session.drain_responses() == []
        assert session._output_audio_gate_state == "gating"

        trailing_noise = b"\xfb" * 320
        speech = b"\x00" * 320
        session._handle_server_message(
            self._server_output(
                trailing_noise + speech,
                text="Your prompt",
                turn_completed=True,
            )
        )
        responses = list(session.iter_turn_responses(timeout=0.1))

        assert [response["response_type"] for response in responses] == [
            "chunk",
            "final",
        ]
        assert responses[0]["audio_content"] == b"\xfb" * 800 + speech
        assert responses[1]["audio_content"] == b""
        assert session._output_audio_gate_state == "inspect"

    def test_trims_long_low_energy_prefix_inside_one_ces_frame(self, connector):
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-leading-prefix",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
        )
        long_low_energy_prefix = b"\xfb" * (
            connector.output_sample_rate_hertz * 6
        )
        speech = b"\x00" * 320

        session._handle_server_message(
            self._server_output(
                long_low_energy_prefix + speech,
                turn_completed=True,
            )
        )
        responses = list(session.iter_turn_responses(timeout=0.1))

        assert responses[0]["audio_content"] == b"\xfb" * 800 + speech

    def test_preserves_short_low_energy_ces_frame(self, connector):
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-short-pause",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
        )
        natural_pause = b"\xfb" * 160

        session._handle_server_message(
            self._server_output(natural_pause, turn_completed=True)
        )
        responses = list(session.iter_turn_responses(timeout=0.1))

        assert responses[0]["audio_content"] == natural_pause

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

        assert len(responses) == 1
        assert responses[0]["message_type"] == "session_end"
        assert responses[0]["output_events"] == []
        assert session.terminal_decision.reason == GECXTerminalReason.NORMAL_END

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
        assert len(responses) == 1
        assert responses[0]["message_type"] == "transfer"
        assert responses[0]["output_events"] == []

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

    def test_session_output_end_session_uses_nested_metadata(self, connector):
        session = GECXStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
        )
        text_message = SimpleNamespace(
            recognition_result=None,
            interruption_signal=None,
            end_session=None,
            go_away=None,
            session_output=SimpleNamespace(
                text="Certainly. Let me connect you with a hotel specialist.",
                audio=b"",
                turn_completed=False,
                end_session=False,
            ),
        )
        terminal_message = SimpleNamespace(
            recognition_result=None,
            interruption_signal=None,
            end_session=None,
            go_away=None,
            session_output=SimpleNamespace(
                text="",
                audio=b"transfer audio",
                turn_completed=True,
                end_session=SimpleNamespace(
                    metadata={"session_escalated": True}
                ),
            ),
        )

        session._handle_server_message(text_message)
        assert session.drain_responses() == []
        session._handle_server_message(terminal_message)

        assert session.terminal_decision.reason == GECXTerminalReason.ESCALATION
        responses = session.drain_responses()
        assert [response["message_type"] for response in responses] == [
            "audio",
            "transfer",
        ]
        assert responses[0]["text"] == ""
        assert responses[0]["response_type"] == "chunk"
        assert responses[0]["audio_content"] == b"transfer audio"
        assert responses[0]["output_events"] == []
        assert responses[1]["text"] == ""
        assert responses[1]["audio_content"] == b""
        assert responses[1]["response_type"] == "final"

    def test_configurable_escalation_alias_remains_supported(self, connector):
        connector.transfer_metadata_keys = ["custom_handoff"]
        responses = self._end_session(connector, {"custom_handoff": "yes"})
        assert responses[0]["message_type"] == "transfer"

    def test_terminal_logs_metadata_keys_without_values(self, connector, caplog):
        caplog.set_level(logging.INFO)

        self._end_session(
            connector,
            {
                "session_escalated": True,
                "customer_email": "guest@example.com",
                "reason": "private routing identifier",
            },
        )

        assert "customer_email" in caplog.text
        assert "guest@example.com" not in caplog.text
        assert "private routing identifier" not in caplog.text

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

    def test_go_away_ends_session_without_reconnection(self, connector):
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
            end_session=None,
            go_away=SimpleNamespace(),
        )

        session._handle_server_message(message)

        assert session.terminal_decision.reason == GECXTerminalReason.GO_AWAY
        assert session.drain_responses()[0]["message_type"] == "session_end"

    def test_initial_escalation_streams_greeting_before_transfer_final(
        self, connector
    ):
        greeting_chunk = connector.create_response(
            conversation_id="conv-1",
            message_type="audio",
            audio_content=b"greeting",
            barge_in_enabled=False,
            response_type="chunk",
        )
        terminal_response = connector.create_response(
            conversation_id="conv-1",
            message_type="transfer",
            barge_in_enabled=False,
            response_type="final",
        )
        stream_session = MagicMock()
        stream_session.iter_turn_responses.return_value = iter(
            [greeting_chunk, terminal_response]
        )

        with patch(
            "src.connectors.gecx_connector.GECXStreamingSession",
            return_value=stream_session,
        ):
            responses = list(connector.start_conversation("conv-1", {}))

        assert [response["message_type"] for response in responses] == [
            "audio",
            "transfer",
        ]
        assert responses[0]["audio_content"] == b"greeting"
        assert responses[0]["response_type"] == "chunk"
        assert responses[1]["audio_content"] == b""
        assert responses[1]["text"] == ""
        assert responses[1]["response_type"] == "final"


class TestTerminalLifecycle:
    def _session(self, connector):
        return GECXStreamingSession(
            connector=connector,
            conversation_id="conv-1",
            session_path="projects/p/locations/us/apps/a/sessions/s1",
            deployment_path=connector.deployment_path,
        )

    def test_turn_timeout_decides_session_end(self, connector):
        session = self._session(connector)

        responses = list(session.iter_turn_responses(timeout=0))

        assert session.terminal_decision.reason == GECXTerminalReason.TIMEOUT
        assert [response["message_type"] for response in responses] == ["session_end"]

    def test_unexpected_stream_exception_decides_session_end(self, connector):
        session = self._session(connector)
        connector.session_client.bidi_run_session.side_effect = RuntimeError("boom")

        session._run_stream()

        assert session.terminal_decision.reason == GECXTerminalReason.STREAM_ERROR
        assert session.terminal_decision.outcome == GECXTerminalOutcome.SESSION_END
        assert session.drain_responses()[0]["message_type"] == "session_end"

    def test_first_terminal_decision_wins_under_race(self, connector):
        session = self._session(connector)
        barrier = threading.Barrier(3)
        results = []

        def decide(reason, outcome):
            barrier.wait()
            results.append(session.terminate(reason, outcome, "race_test"))

        threads = [
            threading.Thread(
                target=decide,
                args=(GECXTerminalReason.NORMAL_END, GECXTerminalOutcome.SESSION_END),
            ),
            threading.Thread(
                target=decide,
                args=(GECXTerminalReason.ESCALATION, GECXTerminalOutcome.TRANSFER),
            ),
        ]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join()

        assert sorted(results) == [False, True]
        assert len(session.drain_responses()) == 1
        queued_items = []
        while not session.inbound_queue.empty():
            queued_items.append(session.inbound_queue.get_nowait())
        assert queued_items.count(_STREAM_STOP) == 1

    def test_duplicate_end_and_late_output_are_suppressed(self, connector):
        session = self._session(connector)
        normal_end = SimpleNamespace(
            recognition_result=None,
            interruption_signal=None,
            session_output=None,
            go_away=None,
            end_session=SimpleNamespace(metadata={}),
        )
        late_output = SimpleNamespace(
            recognition_result=None,
            interruption_signal=None,
            end_session=None,
            go_away=None,
            session_output=SimpleNamespace(
                text="late prompt",
                audio=b"late audio",
                turn_completed=True,
                end_session=False,
            ),
        )

        session._handle_server_message(normal_end)
        session._handle_server_message(normal_end)
        session._handle_server_message(late_output)

        responses = session.drain_responses()
        assert [response["message_type"] for response in responses] == ["session_end"]
        assert session.enqueue_audio(b"late caller audio") is False

    def test_agent_output_before_terminal_is_preserved(self, connector):
        session = self._session(connector)
        output = SimpleNamespace(
            recognition_result=None,
            interruption_signal=None,
            end_session=None,
            go_away=None,
            session_output=SimpleNamespace(
                text="I can help with that",
                audio=b"",
                turn_completed=False,
                end_session=False,
            ),
        )

        session._handle_server_message(output)
        session._handle_end_session("conv-1", SimpleNamespace(metadata={}))

        responses = session.drain_responses()
        assert [response["message_type"] for response in responses] == [
            "session_end"
        ]
        assert responses[0]["text"] == "I can help with that"
        assert responses[0]["response_type"] == "final"

    def test_streamed_agent_audio_precedes_terminal_final(self, connector):
        session = self._session(connector)
        session._emit_active_audio_chunk(b"agent audio")

        session.terminate(
            GECXTerminalReason.GO_AWAY,
            GECXTerminalOutcome.SESSION_END,
            "test_go_away",
        )

        responses = session.drain_responses()
        assert [response["message_type"] for response in responses] == [
            "audio",
            "session_end",
        ]
        assert responses[0]["audio_content"] == b"agent audio"
        assert responses[0]["response_type"] == "chunk"
        assert responses[1]["response_type"] == "final"
        assert sum(
            response["response_type"] == "final" for response in responses
        ) == 1

    def test_delayed_end_session_replaces_normal_final_after_streamed_audio(
        self, connector
    ):
        session = self._session(connector)
        session.begin_input_turn()
        session._handle_server_message(
            SimpleNamespace(
                recognition_result=None,
                interruption_signal=None,
                end_session=None,
                go_away=None,
                session_output=SimpleNamespace(
                    text="Thank you. Have a great day.",
                    audio=b"goodbye audio",
                    turn_completed=True,
                    end_session=False,
                ),
            )
        )
        responses = session.iter_turn_responses(
            timeout=1.0,
            terminal_grace_seconds=1.0,
        )

        first_chunk = next(responses)
        session._handle_end_session("conv-1", SimpleNamespace(metadata={}))
        remaining = list(responses)

        assert first_chunk["response_type"] == "chunk"
        assert first_chunk["audio_content"] == b"goodbye audio"
        assert [response["message_type"] for response in remaining] == [
            "session_end"
        ]
        assert remaining[0]["response_type"] == "final"

    @pytest.mark.parametrize(
        ("gateway_reason", "terminal_reason"),
        [
            ("client_cancelled", GECXTerminalReason.CLIENT_CANCELLED),
            ("client_half_close", GECXTerminalReason.CLIENT_HALF_CLOSE),
            ("gateway_shutdown", GECXTerminalReason.EXPLICIT_SHUTDOWN),
        ],
    )
    def test_gateway_cleanup_is_silent(self, connector, gateway_reason, terminal_reason):
        session = self._session(connector)
        connector.streaming_sessions["conv-1"] = session

        connector.end_conversation(
            "conv-1", {"termination_reason": gateway_reason}
        )

        assert session.terminal_decision.reason == terminal_reason
        assert session.terminal_decision.outcome == GECXTerminalOutcome.SILENT
        assert session.drain_responses() == []
        assert "conv-1" not in connector.streaming_sessions


class TestAudioFormat:
    @pytest.mark.parametrize(
        ("encoding", "expected_byte", "expected_chunk_size"),
        [
            ("MULAW", b"\xff", 800),
            ("ALAW", b"\xd5", 800),
            ("LINEAR16", b"\x00", 1600),
        ],
    )
    def test_endpointing_silence_matches_input_codec(
        self, connector, encoding, expected_byte, expected_chunk_size
    ):
        connector.input_audio_encoding = encoding

        chunks = connector.endpointing_silence_chunks()

        assert len(chunks) == connector.endpointing_silence_ms // 100
        assert all(
            chunk == expected_byte * expected_chunk_size for chunk in chunks
        )

    def test_resolve_input_format_from_nested_gateway_metadata(self, connector):
        rate, encoding = connector._resolve_input_format(
            b"\x00" * 640,
            {
                "audio_metadata": {
                    "sample_rate_hertz": 16000,
                    "encoding": 1,
                }
            },
            "conv-1",
        )
        assert rate == 16000
        assert encoding == "LINEAR_16"

    def test_resolve_input_format_accepts_legacy_flat_metadata(self, connector):
        rate, encoding = connector._resolve_input_format(
            b"\x00" * 640,
            {"sample_rate_hertz": 8000, "encoding": 2},
            "conv-1",
        )
        assert (rate, encoding) == (8000, "MULAW")

    def test_ces_audio_encoding_mulaw(self):
        with patch("src.connectors.gecx_connector.ces_v1") as mock_ces:
            mock_ces.AudioEncoding.MULAW = 2
            assert _ces_audio_encoding("MULAW") == 2


class TestSendMessage:
    def test_send_message_enqueues_audio_and_drains_responses(self, connector):
        stream_session = MagicMock()
        stream_session.is_terminal = False
        stream_session.enqueue_audio.return_value = True
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


class TestSpeechBoundaries:
    def test_declares_streaming_audio_delivery(self, connector):
        assert connector.get_audio_delivery_mode() == "streaming"

    def test_opts_into_client_stream_end_cleanup(self, connector):
        assert connector.should_cleanup_on_client_stream_end() is True

    def test_opts_into_coalesced_speech_end_response(self, connector):
        assert connector.should_coalesce_speech_end_with_response() is True

    def test_speech_started_resets_turn_completion(self, connector):
        stream_session = MagicMock()
        stream_session.is_terminal = False

        with patch.object(connector, "streaming_sessions", {"conv-1": stream_session}):
            responses = list(
                connector.handle_speech_boundary(
                    "conv-1",
                    {"speech_boundary": {"kind": "speech_started"}},
                )
            )

        assert responses == []
        stream_session.begin_input_turn.assert_called_once_with(
            expect_recognition=True
        )

    def test_speech_ended_yields_streamed_turn_responses(self, connector):
        stream_session = MagicMock()
        stream_session.is_terminal = False
        chunk = connector.create_response(
            conversation_id="conv-1",
            message_type="audio",
            audio_content=b"raw audio",
            response_type="chunk",
        )
        final = connector.create_response(
            conversation_id="conv-1",
            response_type="final",
        )
        stream_session.iter_turn_responses.return_value = iter([chunk, final])

        with patch.object(connector, "streaming_sessions", {"conv-1": stream_session}):
            responses = list(
                connector.handle_speech_boundary(
                    "conv-1",
                    {"speech_boundary": {"kind": "speech_ended"}},
                )
            )

        assert responses == [chunk, final]
        stream_session.end_audio_turn.assert_called_once_with()
        stream_session.iter_turn_responses.assert_called_once_with(
            timeout=30.0,
            terminal_grace_seconds=3.0,
        )

    def test_precommitted_speech_end_only_waits_for_response(self, connector):
        stream_session = MagicMock()
        stream_session.is_terminal = False
        stream_session.iter_turn_responses.return_value = iter([])

        with patch.object(connector, "streaming_sessions", {"conv-1": stream_session}):
            responses = list(
                connector.handle_speech_boundary(
                    "conv-1",
                    {
                        "speech_boundary": {"kind": "speech_ended"},
                        "speech_turn_committed": True,
                    },
                )
            )

        assert responses == []
        stream_session.end_audio_turn.assert_not_called()
        stream_session.iter_turn_responses.assert_called_once_with(
            timeout=30.0,
            terminal_grace_seconds=3.0,
        )

    def test_speech_ended_yields_chunks_then_terminal_final(
        self, connector
    ):
        stream_session = MagicMock()
        stream_session.is_terminal = False
        audio = connector.create_response(
            conversation_id="conv-1",
            message_type="audio",
            audio_content=b"raw audio",
            response_type="chunk",
        )
        terminal = connector.create_response(
            conversation_id="conv-1",
            message_type="session_end",
            response_type="final",
        )
        stream_session.iter_turn_responses.return_value = iter([audio, terminal])

        with patch.object(connector, "streaming_sessions", {"conv-1": stream_session}):
            responses = list(
                connector.handle_speech_boundary(
                    "conv-1",
                    {"speech_boundary": {"kind": "speech_ended"}},
                )
            )

        assert responses == [audio, terminal]
        assert sum(
            response["response_type"] == "final" for response in responses
        ) == 1
        stream_session.iter_turn_responses.assert_called_once_with(
            timeout=30.0,
            terminal_grace_seconds=3.0,
        )
