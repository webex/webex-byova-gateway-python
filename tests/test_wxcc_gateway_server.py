"""
Tests for the WxCC Gateway Server.

This module tests the gateway server's ability to handle both single responses
and generator responses from connectors, as well as proper audio input processing.
"""

import threading

import grpc
import pytest
from unittest.mock import MagicMock, patch, Mock
from typing import Iterator, Dict, Any

from src.core.wxcc_gateway_server import ConversationProcessor, WxCCGatewayServer
from src.core.virtual_agent_router import VirtualAgentRouter
from src.generated.byova_common_pb2 import EventInput
from src.generated.voicevirtualagent_pb2 import (
    VoiceInput,
    VoiceVARequest,
    VoiceVAResponse,
)
from src.utils.silero_speech_boundary import SpeechBoundarySignal


class TestConversationProcessor:
    """Test the ConversationProcessor class."""

    @pytest.fixture
    def mock_router(self):
        """Create a mock router for testing."""
        router = MagicMock(spec=VirtualAgentRouter)
        router.should_coalesce_speech_end_with_response.return_value = False
        return router

    @pytest.fixture
    def mock_grpc_request(self):
        """Create a mock gRPC request for testing."""
        request = MagicMock()
        request.conversation_id = "test_conv_123"
        request.virtual_agent_id = "test_agent_456"
        return request

    @pytest.fixture
    def processor(self, mock_router, mock_grpc_request):
        """Create a ConversationProcessor instance for testing."""
        processor = ConversationProcessor(
            conversation_id="test_conv_123",
            virtual_agent_id="test_agent_456",
            router=mock_router
        )
        return processor

    @pytest.fixture
    def mock_audio_input(self):
        """Create a mock audio input for testing."""
        audio_input = MagicMock()
        audio_input.caller_audio = b"test_audio_bytes"
        audio_input.encoding = 2  # MULAW_FORMAT
        audio_input.sample_rate_hertz = 8000
        audio_input.language_code = "en-US"
        audio_input.is_single_utterance = False
        return audio_input

    @pytest.fixture
    def mock_dtmf_input(self):
        """Create a mock DTMF input for testing."""
        dtmf_input = MagicMock()
        dtmf_input.dtmf_events = [1, 2, 3]
        return dtmf_input

    @pytest.fixture
    def mock_event_input(self):
        """Create a mock event input for testing."""
        event_input = MagicMock()
        event_input.event_type = 5  # CUSTOM_EVENT instead of SESSION_START
        event_input.name = "custom_event"
        event_input.parameters = {}
        return event_input

    def test_process_audio_input_single_response(self, processor, mock_router, mock_audio_input):
        """Test processing audio input with a single response from connector."""
        # Mock connector returning single response
        mock_response = {
            "message_type": "response",
            "text": "Hello, how can I help you?",
            "audio_content": b"audio_response_bytes",
            "barge_in_enabled": True
        }
        mock_router.route_request.return_value = mock_response

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify router was called correctly
        mock_router.route_request.assert_called_once_with(
            "test_agent_456",
            "send_message",
            "test_conv_123",
            {
                "conversation_id": "test_conv_123",
                "virtual_agent_id": "test_agent_456",
                "input_type": "audio",
                "audio_data": b"test_audio_bytes",
                "audio_metadata": {
                    "encoding": 2,
                    "sample_rate_hertz": 8000,
                    "language_code": "en-US",
                },
            }
        )

        # Verify response was processed
        assert len(responses) == 1
        assert responses[0].prompts[0].text == "Hello, how can I help you?"
        assert responses[0].prompts[0].audio_content == b"audio_response_bytes"

    def test_initial_escalation_streams_chunk_before_transfer_final(
        self, processor, mock_router
    ):
        raw_audio = b"\xff" * 800
        audio_response = {
            "message_type": "audio",
            "text": "",
            "audio_content": raw_audio,
            "barge_in_enabled": False,
            "response_type": "chunk",
        }
        terminal_response = {
            "message_type": "transfer",
            "text": "",
            "audio_content": b"",
            "barge_in_enabled": False,
            "response_type": "final",
        }
        mock_router.route_request.return_value = iter(
            [audio_response, terminal_response]
        )

        responses = list(processor._start_conversation())

        assert len(responses) == 2
        assert responses[0].response_type == VoiceVAResponse.ResponseType.CHUNK
        assert responses[0].prompts[0].audio_content == raw_audio
        assert responses[0].output_events == []
        assert responses[1].response_type == VoiceVAResponse.ResponseType.FINAL
        assert responses[1].prompts == []
        assert [event.event_type for event in responses[1].output_events] == [2]

    def test_process_audio_input_uses_configured_rate_when_wxcc_omits_it(self, mock_router):
        processor = ConversationProcessor(
            conversation_id="test_conv_123",
            virtual_agent_id="test_agent_456",
            router=mock_router,
            vad_config={"fallback_sample_rate_hertz": 16000},
        )
        processor.speech_boundary_observer = MagicMock()
        processor.speech_boundary_observer.observe.return_value = []
        mock_router.route_request.return_value = None

        audio_input = MagicMock(
            caller_audio=b"\x00\x80\xff\x7f",
            encoding=VoiceInput.VoiceEncoding.LINEAR16_FORMAT,
            sample_rate_hertz=0,
            language_code="en-US",
        )

        assert list(processor._process_audio_input(audio_input)) == []
        frame = processor.speech_boundary_observer.observe.call_args.args[0]
        assert frame.sample_rate_hertz == 16000

    def test_gateway_emits_chunk_typed_speech_started_event(
        self, processor, mock_router, mock_audio_input
    ):
        processor.speech_boundary_observer = MagicMock()
        processor.speech_boundary_observer.observe.return_value = [
            SpeechBoundarySignal("speech_started", "test_conv_123", 8000)
        ]
        mock_router.route_request.return_value = None
        mock_router.should_observe_speech_boundaries.return_value = True
        mock_router.should_coalesce_speech_end_with_response.return_value = True

        responses = list(processor._process_audio_input(mock_audio_input))

        assert len(responses) == 1
        assert responses[0].response_type == VoiceVAResponse.ResponseType.CHUNK
        assert responses[0].output_events[0].event_type == 4
        assert responses[0].output_events[0].name == ""

    def test_gateway_flushes_lex_once_after_speech_ended(
        self, processor, mock_router, mock_audio_input
    ):
        processor.speech_boundary_observer = MagicMock()
        processor.speech_boundary_observer.observe.return_value = [
            SpeechBoundarySignal("speech_ended", "test_conv_123", 8000)
        ]
        lex_response = {
            "message_type": "response",
            "text": "Lex reply",
            "audio_content": b"",
            "barge_in_enabled": False,
        }
        mock_router.route_request.side_effect = [None, iter([lex_response])]
        mock_router.should_observe_speech_boundaries.return_value = True

        responses = list(processor._process_audio_input(mock_audio_input))

        assert len(responses) == 2
        assert responses[0].output_events[0].event_type == 5
        assert responses[1].prompts[0].text == "Lex reply"
        assert mock_router.route_request.call_count == 2
        assert mock_router.route_request.call_args_list[1].args[1] == (
            "handle_speech_boundary"
        )
        assert mock_router.route_request.call_args_list[1].args[3] == {
            "conversation_id": "test_conv_123",
            "virtual_agent_id": "test_agent_456",
            "input_type": "speech_boundary",
            "speech_boundary": {"kind": "speech_ended"},
        }

    def test_gateway_sends_gecx_speech_end_before_normal_prompt(
        self, processor, mock_router, mock_audio_input
    ):
        """Keep END_OF_INPUT ahead of raw audio chunks and one normal FINAL."""
        processor.speech_boundary_observer = MagicMock()
        processor.speech_boundary_observer.observe.return_value = [
            SpeechBoundarySignal("speech_ended", "test_conv_123", 8000)
        ]
        raw_audio = b"\xff" * 800
        audio_response = {
            "message_type": "audio",
            "text": "",
            "audio_content": raw_audio,
            "barge_in_enabled": False,
            "output_events": [],
            "response_type": "chunk",
        }
        final_response = {
            "message_type": "silence",
            "text": "",
            "audio_content": b"",
            "barge_in_enabled": False,
            "output_events": [],
            "response_type": "final",
        }
        mock_router.route_request.side_effect = [
            None,
            iter([audio_response, final_response]),
        ]
        mock_router.should_observe_speech_boundaries.return_value = True
        mock_router.should_coalesce_speech_end_with_response.return_value = True

        responses = list(processor._process_audio_input(mock_audio_input))

        assert len(responses) == 3
        assert responses[0].prompts == []
        assert [event.event_type for event in responses[0].output_events] == [5]
        assert responses[0].response_type == VoiceVAResponse.ResponseType.CHUNK
        assert responses[1].response_type == VoiceVAResponse.ResponseType.CHUNK
        assert responses[1].prompts[0].audio_content == raw_audio
        assert responses[1].prompts[0].text == ""
        assert responses[1].output_events == []
        assert responses[2].response_type == VoiceVAResponse.ResponseType.FINAL
        assert responses[2].prompts == []
        assert sum(
            response.response_type == VoiceVAResponse.ResponseType.FINAL
            for response in responses
        ) == 1

    def test_gateway_does_not_materialize_gecx_chunk_stream(
        self, processor, mock_router
    ):
        raw_audio = b"\xff" * 800
        release_final = threading.Event()

        def connector_responses():
            yield {
                "message_type": "audio",
                "text": "",
                "audio_content": raw_audio,
                "barge_in_enabled": False,
                "output_events": [],
                "response_type": "chunk",
            }
            assert release_final.wait(1.0)
            yield {
                "message_type": "silence",
                "text": "",
                "audio_content": b"",
                "barge_in_enabled": False,
                "output_events": [],
                "response_type": "final",
            }

        mock_router.should_coalesce_speech_end_with_response.return_value = True
        mock_router.route_request.return_value = connector_responses()
        responses = processor._process_speech_boundary(
            SpeechBoundarySignal("speech_ended", "test_conv_123", 8000)
        )

        end_of_input = next(responses)
        first_chunk = next(responses)

        assert end_of_input.response_type == VoiceVAResponse.ResponseType.CHUNK
        assert [event.event_type for event in end_of_input.output_events] == [5]
        assert first_chunk.response_type == VoiceVAResponse.ResponseType.CHUNK
        assert first_chunk.prompts[0].audio_content == raw_audio

        release_final.set()
        final = next(responses)
        assert final.response_type == VoiceVAResponse.ResponseType.FINAL
        with pytest.raises(StopIteration):
            next(responses)

    def test_gateway_streams_gecx_transfer_after_chunk_typed_speech_end(
        self, processor, mock_router, mock_audio_input
    ):
        processor.speech_boundary_observer = MagicMock()
        processor.speech_boundary_observer.observe.return_value = [
            SpeechBoundarySignal("speech_ended", "test_conv_123", 8000)
        ]
        raw_audio = b"\xff" * 800
        audio_response = {
            "message_type": "audio",
            "text": "",
            "audio_content": raw_audio,
            "barge_in_enabled": False,
            "output_events": [],
            "response_type": "chunk",
        }
        transfer_response = {
            "message_type": "transfer",
            "text": "",
            "audio_content": b"",
            "barge_in_enabled": False,
            "output_events": [],
            "response_type": "final",
        }
        mock_router.route_request.side_effect = [
            None,
            iter([audio_response, transfer_response]),
        ]
        mock_router.should_observe_speech_boundaries.return_value = True
        mock_router.should_coalesce_speech_end_with_response.return_value = True

        responses = list(processor._process_audio_input(mock_audio_input))

        assert len(responses) == 3
        assert responses[0].prompts == []
        assert [event.event_type for event in responses[0].output_events] == [5]
        assert responses[0].response_type == VoiceVAResponse.ResponseType.CHUNK
        assert responses[1].response_type == VoiceVAResponse.ResponseType.CHUNK
        assert responses[1].prompts[0].audio_content == raw_audio
        assert responses[1].prompts[0].text == ""
        assert responses[1].output_events == []
        assert responses[2].response_type == VoiceVAResponse.ResponseType.FINAL
        assert responses[2].prompts == []
        assert [event.event_type for event in responses[2].output_events] == [2]

    def test_gateway_merges_speech_resumed_during_end_grace(
        self, processor, mock_router, mock_audio_input
    ):
        class FakeTimer:
            instances = []

            def __init__(self, interval, callback):
                self.interval = interval
                self.callback = callback
                self.cancelled = False
                self.daemon = False
                self.__class__.instances.append(self)

            def start(self):
                return None

            def cancel(self):
                self.cancelled = True

        signals = iter(
            [
                [SpeechBoundarySignal("speech_started", "test_conv_123", 8000)],
                [SpeechBoundarySignal("speech_ended", "test_conv_123", 8000)],
                [SpeechBoundarySignal("speech_started", "test_conv_123", 8000)],
                [SpeechBoundarySignal("speech_ended", "test_conv_123", 8000)],
            ]
        )
        processor.speech_boundary_observer = MagicMock(
            end_silence_ms=1000
        )
        processor.speech_boundary_observer.observe.side_effect = (
            lambda _frame: next(signals)
        )
        mock_router.should_observe_speech_boundaries.return_value = True
        mock_router.should_merge_speech_pauses.return_value = True
        mock_router.should_coalesce_speech_end_with_response.return_value = True
        audio_response = {
            "message_type": "audio",
            "text": "Which dates would you like?",
            "audio_content": b"RIFFaudio",
            "output_events": [],
        }

        def route_request(_agent_id, operation, _conversation_id, *args):
            if operation in {
                "send_message",
                "pause_speech_turn",
                "resume_speech_turn",
                "commit_speech_turn",
            }:
                return None
            if operation == "handle_speech_boundary":
                boundary_kind = args[0]["speech_boundary"]["kind"]
                return (
                    iter([audio_response])
                    if boundary_kind == "speech_ended"
                    else None
                )
            raise AssertionError(f"unexpected operation: {operation}")

        mock_router.route_request.side_effect = route_request
        async_responses = []
        processor.set_async_response_sink(
            lambda response: not async_responses.append(response)
        )

        with patch(
            "src.core.wxcc_gateway_server.threading.Timer", FakeTimer
        ):
            first = list(processor._process_audio_input(mock_audio_input))
            held_end = list(processor._process_audio_input(mock_audio_input))
            resumed = list(processor._process_audio_input(mock_audio_input))
            final_end = list(processor._process_audio_input(mock_audio_input))

            assert len(first) == 1
            assert first[0].output_events[0].event_type == 4
            assert held_end == []
            assert resumed == []
            assert final_end == []
            assert len(FakeTimer.instances) == 2
            assert [timer.interval for timer in FakeTimer.instances] == [1.0, 1.0]
            assert FakeTimer.instances[0].cancelled is True

            FakeTimer.instances[1].callback()

        assert len(async_responses) == 2
        assert async_responses[0].output_events[0].event_type == 5
        assert async_responses[1].prompts[0].text == "Which dates would you like?"
        assert processor.has_async_work() is False
        operations = [
            call.args[1] for call in mock_router.route_request.call_args_list
        ]
        assert operations.count("pause_speech_turn") == 2
        assert operations.count("resume_speech_turn") == 1
        assert operations.count("commit_speech_turn") == 1
        assert operations.count("handle_speech_boundary") == 2

    @pytest.mark.parametrize(
        ("configured_grace_ms", "expected_grace_ms"),
        [
            (None, 1000),
            (-1, 0),
            (2500, 2000),
        ],
    )
    def test_gateway_bounds_speech_end_grace(
        self,
        mock_router,
        configured_grace_ms,
        expected_grace_ms,
    ):
        vad_config = {}
        if configured_grace_ms is not None:
            vad_config["speech_end_grace_ms"] = configured_grace_ms

        processor = ConversationProcessor(
            conversation_id="test_conv_123",
            virtual_agent_id="test_agent_456",
            router=mock_router,
            vad_config=vad_config,
        )

        assert processor.speech_end_grace_ms == expected_grace_ms

    def test_gateway_suppresses_overlapping_boundaries_while_response_pending(
        self, processor, mock_router, mock_audio_input
    ):
        class FakeTimer:
            instances = []

            def __init__(self, interval, callback):
                self.interval = interval
                self.callback = callback
                self.daemon = False
                self.__class__.instances.append(self)

            def start(self):
                return None

            def cancel(self):
                return None

        signals = iter(
            [
                [SpeechBoundarySignal("speech_started", "test_conv_123", 8000)],
                [SpeechBoundarySignal("speech_ended", "test_conv_123", 8000)],
                [SpeechBoundarySignal("speech_started", "test_conv_123", 8000)],
                [SpeechBoundarySignal("speech_ended", "test_conv_123", 8000)],
            ]
        )
        processor.speech_boundary_observer = MagicMock(end_silence_ms=1000)
        processor.speech_boundary_observer.observe.side_effect = (
            lambda _frame: next(signals)
        )
        mock_router.should_observe_speech_boundaries.return_value = True
        mock_router.should_merge_speech_pauses.return_value = True
        mock_router.should_coalesce_speech_end_with_response.return_value = True
        response_waiting = threading.Event()
        release_response = threading.Event()
        audio_response = {
            "message_type": "audio",
            "text": "Complete request received",
            "audio_content": b"RIFFaudio",
            "output_events": [],
        }

        def delayed_response():
            response_waiting.set()
            assert release_response.wait(1.0)
            yield audio_response

        def route_request(_agent_id, operation, _conversation_id, *args):
            if operation in {
                "send_message",
                "pause_speech_turn",
                "resume_speech_turn",
                "commit_speech_turn",
            }:
                return None
            if operation == "handle_speech_boundary":
                boundary_kind = args[0]["speech_boundary"]["kind"]
                return (
                    delayed_response()
                    if boundary_kind == "speech_ended"
                    else None
                )
            raise AssertionError(f"unexpected operation: {operation}")

        mock_router.route_request.side_effect = route_request
        async_responses = []
        processor.set_async_response_sink(
            lambda response: not async_responses.append(response)
        )

        with patch(
            "src.core.wxcc_gateway_server.threading.Timer", FakeTimer
        ):
            first = list(processor._process_audio_input(mock_audio_input))
            assert list(processor._process_audio_input(mock_audio_input)) == []

            first_waiter = threading.Thread(
                target=FakeTimer.instances[0].callback
            )
            first_waiter.start()
            assert response_waiting.wait(1.0)

            resumed = list(processor._process_audio_input(mock_audio_input))
            assert list(processor._process_audio_input(mock_audio_input)) == []
            FakeTimer.instances[1].callback()
            release_response.set()
            first_waiter.join(timeout=1.0)

        assert not first_waiter.is_alive()
        assert len(first) == 1
        assert first[0].output_events[0].event_type == 4
        assert resumed == []
        assert len(async_responses) == 2
        assert async_responses[0].output_events[0].event_type == 5
        assert async_responses[1].prompts[0].text == "Complete request received"
        operations = [
            call.args[1] for call in mock_router.route_request.call_args_list
        ]
        assert operations.count("pause_speech_turn") == 2
        assert operations.count("commit_speech_turn") == 2
        assert operations.count("handle_speech_boundary") == 3
        assert processor.has_async_work() is False

    def test_gateway_suppresses_delayed_terminal_after_stream_cancellation(
        self, processor
    ):
        wav_audio = bytearray(44 + 8000)
        wav_audio[:4] = b"RIFF"
        wav_audio[8:12] = b"WAVE"
        wav_audio[28:32] = (8000).to_bytes(4, "little")
        wav_audio[36:40] = b"data"
        wav_audio[40:44] = (8000).to_bytes(4, "little")
        responses = iter(
            [
                {
                    "message_type": "audio",
                    "text": "Transferring now.",
                    "audio_content": bytes(wav_audio),
                },
                {"message_type": "transfer", "text": "", "audio_content": b""},
            ]
        )
        cancel_event = MagicMock()
        cancel_event.wait.return_value = True
        processor.set_stream_cancel_event(cancel_event)

        grpc_responses = list(
            processor._iter_grpc_connector_responses(
                responses, delay_terminal_after_audio=True
            )
        )

        assert len(grpc_responses) == 1
        assert grpc_responses[0].prompts[0].audio_content == bytes(wav_audio)
        cancel_event.wait.assert_called_once_with(1.0)

    def test_gateway_caps_response_derived_terminal_playback_wait(self, processor):
        wav_audio = bytearray(44 + 8000)
        wav_audio[:4] = b"RIFF"
        wav_audio[8:12] = b"WAVE"
        wav_audio[28:32] = (8000).to_bytes(4, "little")
        wav_audio[36:40] = b"data"
        wav_audio[40:44] = (8000).to_bytes(4, "little")
        cancel_event = MagicMock()
        cancel_event.wait.return_value = False
        processor.set_stream_cancel_event(cancel_event)
        processor.max_terminal_playback_seconds = 0.25

        list(
            processor._iter_grpc_connector_responses(
                iter(
                    [
                        {
                            "message_type": "audio",
                            "text": "Transferring now.",
                            "audio_content": bytes(wav_audio),
                        },
                        {
                            "message_type": "transfer",
                            "text": "",
                            "audio_content": b"",
                        },
                    ]
                ),
                delay_terminal_after_audio=True,
            )
        )

        cancel_event.wait.assert_called_once_with(0.25)

    def test_gateway_skips_vad_during_connector_dtmf_mode(
        self, processor, mock_router, mock_audio_input
    ):
        processor.speech_boundary_observer = MagicMock()
        mock_router.route_request.return_value = None
        mock_router.should_observe_speech_boundaries.return_value = False

        assert list(processor._process_audio_input(mock_audio_input)) == []

        mock_router.route_request.assert_called_once()
        processor.speech_boundary_observer.observe.assert_not_called()

    def test_process_audio_input_with_session_end_event(self, processor, mock_router, mock_audio_input):
        """Test processing audio input with SESSION_END event from connector."""
        # Mock connector returning session end response
        mock_response = {
            "message_type": "session_end",
            "text": "Thank you for calling. Have a great day!",
            "audio_content": b"",
            "barge_in_enabled": False,
            "response_type": "final"
        }
        mock_router.route_request.return_value = mock_response

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify response was processed
        assert len(responses) == 1
        response = responses[0]
        assert response.prompts[0].text == "Thank you for calling. Have a great day!"
        
        # Verify SESSION_END event was created
        assert len(response.output_events) == 1
        event = response.output_events[0]
        assert event.event_type == 1  # SESSION_END
        assert event.name == "session_ended"
        assert response.input_mode == 0  # INPUT_VOICE_MODE_UNSPECIFIED
        assert not response.HasField("input_handling_config")

    def test_empty_session_end_is_terminal_only_response(self, processor):
        """SESSION_END must not request another caller input turn."""
        response = processor._convert_connector_response_to_grpc(
            {
                "message_type": "session_end",
                "text": "",
                "audio_content": b"",
                "response_type": "final",
            }
        )

        assert response is not None
        assert [field.name for field, _ in response.ListFields()] == ["output_events"]
        assert response.output_events[0].event_type == 1  # SESSION_END
        assert response.output_events[0].name == "session_ended"
        assert processor.can_be_deleted is True

    def test_process_audio_input_with_transfer_to_agent_event(self, processor, mock_router, mock_audio_input):
        """Test processing audio input with TRANSFER_TO_AGENT event from connector."""
        # Mock connector returning transfer response
        mock_response = {
            "message_type": "transfer",
            "text": "Let me transfer you to a human agent.",
            "audio_content": b"ces-transfer-audio",
            "barge_in_enabled": False,
            "response_type": "final"
        }
        mock_router.route_request.return_value = mock_response

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify response was processed
        assert len(responses) == 1
        response = responses[0]
        assert response.prompts[0].text == "Let me transfer you to a human agent."
        assert response.prompts[0].audio_content == b"ces-transfer-audio"
        assert response.prompts[0].is_barge_in_enabled is False
        
        # Verify TRANSFER_TO_AGENT event was created
        assert len(response.output_events) == 1
        event = response.output_events[0]
        assert event.event_type == 2  # TRANSFER_TO_AGENT
        assert event.name == "transfer_requested"

    def test_process_audio_input_with_output_events(self, processor, mock_router, mock_audio_input):
        """Test processing audio input with custom output events from connector."""
        # Mock connector returning response with output events
        mock_response = {
            "message_type": "response",
            "text": "Processing your request...",
            "audio_content": b"",
            "barge_in_enabled": False,
            "response_type": "final",
            "output_events": [
                {
                    "event_type": "SESSION_END",
                    "name": "lex_conversation_ended",
                    "metadata": {
                        "reason": "lex_dialog_closed",
                        "bot_name": "TestBot",
                        "conversation_id": "test_conv_123"
                    }
                }
            ]
        }
        mock_router.route_request.return_value = mock_response

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify response was processed
        assert len(responses) == 1
        response = responses[0]
        assert response.prompts[0].text == "Processing your request..."
        
        # Verify SESSION_END event was created from output_events
        assert len(response.output_events) == 1
        event = response.output_events[0]
        assert event.event_type == 1  # SESSION_END
        assert event.name == "lex_conversation_ended"
        
        # Verify metadata was properly converted
        assert event.metadata["reason"] == "lex_dialog_closed"
        assert event.metadata["bot_name"] == "TestBot"
        assert event.metadata["conversation_id"] == "test_conv_123"

    def test_process_audio_input_with_transfer_to_agent_output_event(self, processor, mock_router, mock_audio_input):
        """Test processing audio input with TRANSFER_TO_AGENT output event from connector."""
        # Mock connector returning response with TRANSFER_TO_AGENT output event
        mock_response = {
            "message_type": "response",
            "text": "I need to transfer you.",
            "audio_content": b"",
            "barge_in_enabled": False,
            "response_type": "final",
            "output_events": [
                {
                    "event_type": "TRANSFER_TO_AGENT",
                    "name": "lex_intent_failed",
                    "metadata": {
                        "reason": "intent_failed",
                        "intent_name": "ComplexRequest",
                        "bot_name": "TestBot",
                        "conversation_id": "test_conv_123"
                    }
                }
            ]
        }
        mock_router.route_request.return_value = mock_response

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify response was processed
        assert len(responses) == 1
        response = responses[0]
        assert response.prompts[0].text == "I need to transfer you."
        
        # Verify TRANSFER_TO_AGENT event was created from output_events
        assert len(response.output_events) == 1
        event = response.output_events[0]
        assert event.event_type == 2  # TRANSFER_TO_AGENT
        assert event.name == "lex_intent_failed"
        
        # Verify metadata was properly converted
        assert event.metadata["reason"] == "intent_failed"
        assert event.metadata["intent_name"] == "ComplexRequest"
        assert event.metadata["bot_name"] == "TestBot"
        assert event.metadata["conversation_id"] == "test_conv_123"

    def test_process_audio_input_generator_response(self, processor, mock_router, mock_audio_input):
        """Test processing audio input with a generator response from connector."""
        # Mock connector returning generator with multiple responses
        def mock_generator():
            yield {
                "message_type": "silence",
                "text": "",
                "audio_content": b"",
                "barge_in_enabled": False
            }
            yield {
                "message_type": "response",
                "text": "I heard you say something",
                "audio_content": b"final_response_bytes",
                "barge_in_enabled": True
            }

        mock_router.route_request.return_value = mock_generator()

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify both responses were processed
        assert len(responses) == 2
        
        # First response should be silence
        assert responses[0].prompts == []  # Silence response has no prompts
        
        # Second response should have content
        assert responses[1].prompts[0].text == "I heard you say something"
        assert responses[1].prompts[0].audio_content == b"final_response_bytes"

    def test_process_audio_input_empty_generator(self, processor, mock_router, mock_audio_input):
        """Test processing audio input with an empty generator response."""
        # Mock connector returning empty generator
        def empty_generator():
            return
            yield  # This will never execute

        mock_router.route_request.return_value = empty_generator()

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify no responses were generated
        assert len(responses) == 0

    def test_process_audio_input_none_response(self, processor, mock_router, mock_audio_input):
        """Test that gateway properly handles None responses from connectors."""
        # Mock connector returning None (when no response is needed)
        mock_router.route_request.return_value = None
        
        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))
        
        # Should skip None responses and return empty list
        assert len(responses) == 0

    def test_process_audio_input_generator_with_none_responses(self, processor, mock_router, mock_audio_input):
        """Test that gateway handles mixed None and valid responses."""
        # Mock connector returning None followed by valid response
        def mock_generator():
            yield None  # No response needed
            yield {     # Valid response
                "message_type": "response",
                "text": "Hello",
                "audio_content": b"audio",
                "barge_in_enabled": True
            }
            yield None  # No response needed

        mock_router.route_request.return_value = mock_generator()
        
        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))
        
        # Should skip None and process valid response
        assert len(responses) == 1
        assert responses[0].prompts[0].text == "Hello"

    def test_process_audio_input_router_error(self, processor, mock_router, mock_audio_input):
        """Test processing audio input when router raises an error."""
        # Mock router to raise an error
        mock_router.route_request.side_effect = Exception("Router error")

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify error response was generated
        assert len(responses) == 1
        assert "Audio processing error: Router error" in str(responses[0])

    def test_process_dtmf_input_single_response(self, processor, mock_router, mock_dtmf_input):
        """Test processing DTMF input with a single response from connector."""
        # Mock connector returning single response
        mock_response = {
            "message_type": "transfer",
            "text": "Transferring you to an agent",
            "audio_content": b"transfer_audio_bytes",
            "barge_in_enabled": False
        }
        mock_router.route_request.return_value = mock_response

        # Process DTMF input
        responses = list(processor._process_dtmf_input(mock_dtmf_input))

        # Verify router was called correctly
        mock_router.route_request.assert_called_once_with(
            "test_agent_456",
            "send_message",
            "test_conv_123",
            {
                "conversation_id": "test_conv_123",
                "virtual_agent_id": "test_agent_456",
                "input_type": "dtmf",
                "dtmf_data": {
                    "dtmf_events": [1, 2, 3]
                }
            }
        )

        # Verify response was processed with FINAL response type
        assert len(responses) == 1
        assert responses[0].response_type == 0  # FINAL
        assert responses[0].prompts[0].text == "Transferring you to an agent"

    def test_process_dtmf_input_generator_response(self, processor, mock_router, mock_dtmf_input):
        """Test processing DTMF input with a generator response from connector."""
        # Mock connector returning generator with multiple responses
        def mock_generator():
            yield {
                "message_type": "processing",
                "text": "Processing your request...",
                "audio_content": b"processing_audio",
                "barge_in_enabled": False
            }
            yield {
                "message_type": "transfer",
                "text": "Transferring you now",
                "audio_content": b"transfer_audio",
                "barge_in_enabled": False
            }

        mock_router.route_request.return_value = mock_generator()

        # Process DTMF input
        responses = list(processor._process_dtmf_input(mock_dtmf_input))

        # Verify both responses were processed
        assert len(responses) == 2
        assert responses[0].response_type == 0  # FINAL
        assert responses[1].response_type == 0  # FINAL

    def test_process_event_input_single_response(self, processor, mock_router, mock_event_input):
        """Test processing event input with a single response from connector."""
        # Mock connector returning single response
        mock_response = {
            "message_type": "event_processed",
            "text": "Event processed successfully",
            "audio_content": b"event_audio_bytes",
            "barge_in_enabled": True
        }
        mock_router.route_request.return_value = mock_response

        # Process event input
        responses = list(processor._process_event_input(mock_event_input))

        # Verify router was called correctly
        mock_router.route_request.assert_called_once_with(
            "test_agent_456",
            "send_message",
            "test_conv_123",
            {
                "conversation_id": "test_conv_123",
                "virtual_agent_id": "test_agent_456",
                "input_type": "event",
                "event_data": {
                    "event_type": 5,
                    "name": "custom_event",
                    "parameters": {}
                }
            }
        )

        # Verify response was processed
        assert len(responses) == 1
        assert responses[0].prompts[0].text == "Event processed successfully"

    def test_process_event_input_generator_response(self, processor, mock_router, mock_event_input):
        """Test processing event input with a generator response from connector."""
        # Mock connector returning generator with multiple responses
        def mock_generator():
            yield {
                "message_type": "event_received",
                "text": "Event received",
                "audio_content": b"event_received_audio",
                "barge_in_enabled": False
            }
            yield {
                "message_type": "event_processed",
                "text": "Event processed",
                "audio_content": b"event_processed_audio",
                "barge_in_enabled": True
            }

        mock_router.route_request.return_value = mock_generator()

        # Process event input
        responses = list(processor._process_event_input(mock_event_input))

        # Verify both responses were processed
        assert len(responses) == 2
        assert responses[0].prompts[0].text == "Event received"
        assert responses[1].prompts[0].text == "Event processed"

    def test_process_session_end_event(self, processor, mock_router):
        """Test processing SESSION_END event from client."""
        from src.generated.byova_common_pb2 import EventInput
        from src.generated.voicevirtualagent_pb2 import VoiceVAResponse
        
        # Create SESSION_END event input
        mock_session_end_event = EventInput()
        mock_session_end_event.event_type = EventInput.EventType.SESSION_END
        mock_session_end_event.name = "call_end"
        mock_session_end_event.parameters = {}
        
        # Mock connector returning response for end_conversation
        mock_end_response = {
            "message_type": "session_end",
            "text": "Conversation ended",
            "audio_content": b"goodbye_audio",
            "barge_in_enabled": False
        }
        mock_router.route_request.return_value = mock_end_response

        # Process SESSION_END event
        responses = list(processor._process_event_input(mock_session_end_event))

        # Verify router was called to end conversation
        mock_router.route_request.assert_called_once_with(
            "test_agent_456",
            "end_conversation",
            "test_conv_123",
            {
                "conversation_id": "test_conv_123",
                "virtual_agent_id": "test_agent_456",
                "input_type": "conversation_end",
                "termination_reason": "client_session_end",
            }
        )

        # Verify conversation is marked for cleanup
        assert processor.can_be_deleted == True

        # Verify response was processed
        assert len(responses) == 2  # One from connector, one final response
        
        # Check the final response has SESSION_END output event
        final_response = responses[1]
        assert final_response.response_type == VoiceVAResponse.ResponseType.FINAL
        assert len(final_response.output_events) == 1
        assert final_response.output_events[0].event_type == 1  # SESSION_END
        assert final_response.output_events[0].name == "session_ended_by_client"

    def test_process_session_end_event_with_connector_error(self, processor, mock_router):
        """Test processing SESSION_END event when connector returns error."""
        from src.generated.byova_common_pb2 import EventInput
        from src.generated.voicevirtualagent_pb2 import VoiceVAResponse
        
        # Create SESSION_END event input
        mock_session_end_event = EventInput()
        mock_session_end_event.event_type = EventInput.EventType.SESSION_END
        mock_session_end_event.name = "call_end"
        mock_session_end_event.parameters = {}
        
        # Mock connector raising exception
        mock_router.route_request.side_effect = Exception("Connector error")

        # Process SESSION_END event
        responses = list(processor._process_event_input(mock_session_end_event))

        # Verify conversation is still marked for cleanup even with error
        assert processor.can_be_deleted == True

        # Verify final response is still sent
        assert len(responses) == 1  # Only the final response
        
        # Check the final response has SESSION_END output event
        final_response = responses[0]
        assert final_response.response_type == VoiceVAResponse.ResponseType.FINAL
        assert len(final_response.output_events) == 1
        assert final_response.output_events[0].event_type == 1  # SESSION_END
        assert final_response.output_events[0].name == "session_ended_by_client"

    def test_cleanup_forwards_termination_reason(self, processor, mock_router):
        processor.cleanup("client_half_close")

        mock_router.route_request.assert_called_once_with(
            "test_agent_456",
            "end_conversation",
            "test_conv_123",
            {
                "conversation_id": "test_conv_123",
                "virtual_agent_id": "test_agent_456",
                "input_type": "conversation_end",
                "termination_reason": "client_half_close",
            },
        )

    def test_audio_input_field_access(self, processor, mock_router, mock_audio_input):
        """Test that audio input correctly accesses caller_audio field."""
        # Mock connector returning single response
        mock_response = {
            "message_type": "response",
            "text": "Audio received",
            "audio_content": b"response_audio",
            "barge_in_enabled": True
        }
        mock_router.route_request.return_value = mock_response

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify the correct field was accessed
        assert len(responses) == 1
        
        # Check that the router was called with the correct audio data
        call_args = mock_router.route_request.call_args
        message_data = call_args[0][3]  # Fourth argument is message_data
        assert message_data["audio_data"] == b"test_audio_bytes"
        assert message_data["audio_metadata"] == {
            "encoding": 2,
            "sample_rate_hertz": 8000,
            "language_code": "en-US",
        }

    def test_backward_compatibility_single_responses(self, processor, mock_router, mock_audio_input):
        """Test that single responses still work for backward compatibility."""
        # Mock connector returning single response (old pattern)
        mock_response = {
            "message_type": "response",
            "text": "Backward compatible response",
            "audio_content": b"compat_audio",
            "barge_in_enabled": True
        }
        mock_router.route_request.return_value = mock_response

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify single response was processed correctly
        assert len(responses) == 1
        assert responses[0].prompts[0].text == "Backward compatible response"

    def test_generator_with_none_responses(self, processor, mock_router, mock_audio_input):
        """Test that generator with None responses is handled correctly."""
        # Mock connector returning generator with some None responses
        def mock_generator():
            yield None
            yield {
                "message_type": "response",
                "text": "Valid response",
                "audio_content": b"valid_audio",
                "barge_in_enabled": True
            }
            yield None

        mock_router.route_request.return_value = mock_generator()

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify only valid responses were processed (None responses were filtered out)
        assert len(responses) == 1
        
        # First response should be a valid response (None responses were filtered out)
        assert len(responses[0].prompts) == 1  # Valid response has one prompt
        assert responses[0].prompts[0].text == "Valid response"
        
        # Only one response should be processed (None responses were filtered out)

    def test_generator_with_empty_dict_responses(self, processor, mock_router, mock_audio_input):
        """Test that generator with empty dict responses is handled correctly."""
        # Mock connector returning generator with empty dict responses
        def mock_generator():
            yield {}
            yield {
                "message_type": "response",
                "text": "Valid response",
                "audio_content": b"valid_audio",
                "barge_in_enabled": True
            }
            yield {}

        mock_router.route_request.return_value = mock_generator()

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify all responses were processed (empty dict becomes silence response)
        assert len(responses) == 3
        
        # First response should be a silence response (empty dict becomes silence)
        assert len(responses[0].prompts) == 0  # Silence response has no prompts
        
        # Second response should have content
        assert responses[1].prompts[0].text == "Valid response"
        
        # Third response should also be a silence response
        assert len(responses[2].prompts) == 0  # Silence response has no prompts

    def test_generator_with_silence_responses(self, processor, mock_router, mock_audio_input):
        """Test that generator with silence responses is handled correctly."""
        # Mock connector returning generator with silence responses
        def mock_generator():
            yield {
                "message_type": "silence",
                "text": "",
                "audio_content": b"",
                "barge_in_enabled": False
            }
            yield {
                "message_type": "response",
                "text": "Final response",
                "audio_content": b"final_audio",
                "barge_in_enabled": True
            }

        mock_router.route_request.return_value = mock_generator()

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify both responses were processed
        assert len(responses) == 2
        
        # First response should be silence (no prompts)
        assert len(responses[0].prompts) == 0
        
        # Second response should have content
        assert responses[1].prompts[0].text == "Final response"

    def test_error_handling_in_generator(self, processor, mock_router, mock_audio_input):
        """Test that errors in generator responses are handled gracefully."""
        # Mock connector returning generator that raises an error
        def error_generator():
            yield {
                "message_type": "response",
                "text": "First response",
                "audio_content": b"first_audio",
                "barge_in_enabled": True
            }
            raise Exception("Error in generator")

        mock_router.route_request.return_value = error_generator()

        # Process audio input - should handle the error gracefully
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify error was handled gracefully
        assert len(responses) == 2
        
        # First response should be valid
        assert responses[0].prompts[0].text == "First response"
        
        # Second response should be an error response
        assert "Audio processing error: Error in generator" in str(responses[1])

    def test_mixed_response_types(self, processor, mock_router, mock_audio_input):
        """Test handling of mixed response types (dict, string, bytes)."""
        # Mock connector returning mixed types
        def mixed_generator():
            yield "string_response"  # String response
            yield b"bytes_response"  # Bytes response
            yield {
                "message_type": "response",
                "text": "Dict response",
                "audio_content": b"dict_audio",
                "barge_in_enabled": True
            }

        mock_router.route_request.return_value = mixed_generator()

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify all responses were processed (invalid ones become error responses)
        assert len(responses) == 3
        
        # First response should be an error response (string has no 'get' method)
        assert "str" in responses[0].prompts[0].text
        assert "object has no attribute 'get'" in responses[0].prompts[0].text
        assert responses[0].prompts[0].text.startswith("I'm sorry, I encountered an error:")
        
        # Second response should be an error response (bytes has no 'get' method)
        assert "bytes" in responses[1].prompts[0].text
        assert "object has no attribute 'get'" in responses[1].prompts[0].text
        assert responses[1].prompts[0].text.startswith("I'm sorry, I encountered an error:")
        
        # Third response should be valid
        assert responses[2].prompts[0].text == "Dict response"

    def test_audio_input_with_different_encodings(self, processor, mock_router):
        """Test audio input processing with different encoding types."""
        # Test with LINEAR16 encoding
        audio_input_linear16 = MagicMock()
        audio_input_linear16.caller_audio = b"linear16_audio"
        audio_input_linear16.encoding = 1  # LINEAR16_FORMAT
        audio_input_linear16.sample_rate_hertz = 16000
        audio_input_linear16.language_code = "en-US"
        audio_input_linear16.is_single_utterance = False

        mock_response = {
            "message_type": "response",
            "text": "Linear16 audio processed",
            "audio_content": b"response_audio",
            "barge_in_enabled": True
        }
        mock_router.route_request.return_value = mock_response

        # Process audio input
        responses = list(processor._process_audio_input(audio_input_linear16))

        # Verify processing was successful
        assert len(responses) == 1
        assert responses[0].prompts[0].text == "Linear16 audio processed"

        # Verify the correct audio data was passed
        call_args = mock_router.route_request.call_args
        message_data = call_args[0][3]
        assert message_data["audio_data"] == b"linear16_audio"

    def test_end_of_input_event_conversion(self, processor, mock_router, mock_audio_input):
        """Test that END_OF_INPUT events are properly converted to protobuf format."""
        # Mock connector returning response with END_OF_INPUT event
        mock_response = {
            "message_type": "silence",
            "text": "",
            "audio_content": b"",
            "barge_in_enabled": True,
            "output_events": [
                {
                    "event_type": "END_OF_INPUT",
                    "name": "end_of_input",
                    "metadata": {"silence_duration": 5000, "buffer_size": 1024}
                }
            ]
        }
        mock_router.route_request.return_value = mock_response

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify response was processed
        assert len(responses) == 1
        response = responses[0]
        
        # Verify output events were converted
        assert len(response.output_events) == 1
        event = response.output_events[0]
        
        # Verify event type is correct protobuf enum
        assert event.event_type == 5  # END_OF_INPUT = 5
        
        # Verify event name
        assert event.name == "end_of_input"
        
        # Verify metadata was converted to protobuf Struct
        assert event.metadata is not None
        assert event.metadata["silence_duration"] == 5000
        assert event.metadata["buffer_size"] == 1024

    def test_start_of_input_event_conversion(self, processor, mock_router, mock_audio_input):
        """Test that START_OF_INPUT events are properly converted to protobuf format."""
        # Mock connector returning response with START_OF_INPUT event
        mock_response = {
            "message_type": "silence",
            "text": "",
            "audio_content": b"",
            "barge_in_enabled": True,
            "output_events": [
                {
                    "event_type": "START_OF_INPUT",
                    "name": "",
                    "metadata": None
                }
            ]
        }
        mock_router.route_request.return_value = mock_response

        # Process audio input
        responses = list(processor._process_audio_input(mock_audio_input))

        # Verify response was processed
        assert len(responses) == 1
        response = responses[0]
        
        # Verify output events were converted
        assert len(response.output_events) == 1
        event = response.output_events[0]
        
        # Verify event type is correct protobuf enum
        assert event.event_type == 4  # START_OF_INPUT = 4
        
        # Verify event name is empty string
        assert event.name == ""
        
        # Verify metadata is empty protobuf Struct (protobuf default for message fields)
        assert event.metadata is not None
        # In protobuf, message fields can't be None, they default to empty message


class TestClientStreamEndCleanup:
    @staticmethod
    def _session_start_request():
        return VoiceVARequest(
            conversation_id="stream-end-conv",
            virtual_agent_id="GECX Agent",
            event_input=EventInput(
                event_type=EventInput.EventType.SESSION_START,
                name="call_start",
            ),
        )

    @staticmethod
    def _session_start_response():
        return {
            "message_type": "session_start",
            "text": "Connected",
            "audio_content": b"",
            "barge_in_enabled": False,
            "response_type": "final",
        }

    @staticmethod
    def _custom_event_request():
        return VoiceVARequest(
            conversation_id="stream-end-conv",
            virtual_agent_id="GECX Agent",
            event_input=EventInput(
                event_type=EventInput.EventType.CUSTOM_EVENT,
                name="continue_call",
            ),
        )

    @staticmethod
    def _audio_request(audio_data: bytes) -> VoiceVARequest:
        return VoiceVARequest(
            conversation_id="stream-end-conv",
            virtual_agent_id="GECX Agent",
            audio_input=VoiceInput(
                caller_audio=audio_data,
                encoding=VoiceInput.VoiceEncoding.MULAW_FORMAT,
                sample_rate_hertz=8000,
                language_code="en-US",
            ),
        )

    @pytest.mark.parametrize(
        ("message_type", "expected_event_type"),
        [("session_end", 1), ("transfer", 2)],
    )
    def test_server_terminal_response_completes_stream(
        self, message_type, expected_event_type
    ):
        router = MagicMock(spec=VirtualAgentRouter)

        def route_request(agent_id, operation, conversation_id, message_data):
            if operation == "start_conversation":
                return {
                    "message_type": message_type,
                    "text": "",
                    "audio_content": b"",
                    "response_type": "final",
                }
            if operation == "end_conversation":
                return None
            raise AssertionError(f"Unexpected operation: {operation}")

        router.route_request.side_effect = route_request
        router.should_cleanup_on_client_stream_end.return_value = True
        context = MagicMock()
        context.is_active.return_value = True
        server = WxCCGatewayServer(router)

        def requests():
            yield self._session_start_request()
            yield self._custom_event_request()

        responses = list(server.ProcessCallerInput(requests(), context))

        assert len(responses) == 1
        assert responses[0].output_events[0].event_type == expected_event_type
        assert [
            call.args[1] for call in router.route_request.call_args_list
        ] == ["start_conversation", "end_conversation"]
        assert "stream-end-conv" not in server.conversations
        router.route_request.assert_any_call(
            "GECX Agent",
            "end_conversation",
            "stream-end-conv",
            {
                "conversation_id": "stream-end-conv",
                "virtual_agent_id": "GECX Agent",
                "input_type": "conversation_end",
                "termination_reason": "completed",
            },
        )
        router.should_cleanup_on_client_stream_end.assert_not_called()

    def test_nonterminal_response_keeps_request_stream_open(self):
        router = MagicMock(spec=VirtualAgentRouter)
        router.route_request.side_effect = [self._session_start_response(), None]
        router.should_cleanup_on_client_stream_end.return_value = True
        context = MagicMock()
        context.is_active.return_value = True
        server = WxCCGatewayServer(router)
        consumed_second_request = False

        def requests():
            nonlocal consumed_second_request
            yield self._session_start_request()
            consumed_second_request = True
            yield self._custom_event_request()

        responses = list(server.ProcessCallerInput(requests(), context))

        assert len(responses) == 1
        assert consumed_second_request is True
        assert "stream-end-conv" in server.conversations

    def test_ingress_continues_while_caller_has_not_requested_next_response(
        self
    ):
        router = MagicMock(spec=VirtualAgentRouter)
        router.route_request.side_effect = [self._session_start_response(), None]
        router.should_cleanup_on_client_stream_end.return_value = True
        context = MagicMock()
        context.is_active.return_value = True
        server = WxCCGatewayServer(router)
        allow_second_request = threading.Event()
        consumed_second_request = threading.Event()

        def requests():
            yield self._session_start_request()
            assert allow_second_request.wait(1.0)
            consumed_second_request.set()
            yield self._custom_event_request()

        responses = server.ProcessCallerInput(requests(), context)
        first_response = next(responses)
        allow_second_request.set()

        assert first_response.prompts[0].text == "Connected"
        assert consumed_second_request.wait(1.0)
        assert list(responses) == []

    def test_audio_ingress_is_buffered_while_connector_response_is_producing(
        self
    ):
        router = MagicMock(spec=VirtualAgentRouter)
        allow_response_completion = threading.Event()
        consumed_audio_requests = threading.Event()
        processed_audio_requests = threading.Event()
        processed_audio: list[bytes] = []
        caller_frames = [b"caller-frame-1", b"caller-frame-2", b"caller-frame-3"]

        def start_responses():
            yield self._session_start_response()
            assert allow_response_completion.wait(1.0)
            yield {
                **self._session_start_response(),
                "text": "The first response is complete.",
            }

        def route_request(agent_id, operation, conversation_id, message_data):
            if operation == "start_conversation":
                return start_responses()
            if operation == "send_message":
                processed_audio.append(message_data["audio_data"])
                if len(processed_audio) == len(caller_frames):
                    processed_audio_requests.set()
                return None
            raise AssertionError(f"Unexpected operation: {operation}")

        router.route_request.side_effect = route_request
        router.should_observe_speech_boundaries.return_value = False
        router.should_cleanup_on_client_stream_end.return_value = True
        context = MagicMock()
        context.is_active.return_value = True
        server = WxCCGatewayServer(router)

        def requests():
            yield self._session_start_request()
            for caller_frame in caller_frames:
                yield self._audio_request(caller_frame)
            consumed_audio_requests.set()

        responses = server.ProcessCallerInput(requests(), context)
        first_response = next(responses)

        try:
            assert first_response.prompts[0].text == "Connected"
            assert consumed_audio_requests.wait(0.5)
            assert processed_audio == []
        finally:
            allow_response_completion.set()

        remaining_responses = list(responses)

        assert [response.prompts[0].text for response in remaining_responses] == [
            "The first response is complete."
        ]
        assert processed_audio_requests.is_set()
        assert processed_audio == caller_frames

    def test_bounded_ingress_backpressure_stops_on_stream_cancellation(self):
        router = MagicMock(spec=VirtualAgentRouter)
        allow_response_completion = threading.Event()
        requested_second_buffered_input = threading.Event()
        requested_third_buffered_input = threading.Event()
        existing_thread_ids = {id(thread) for thread in threading.enumerate()}

        def start_responses():
            yield self._session_start_response()
            assert allow_response_completion.wait(1.0)

        router.route_request.side_effect = (
            lambda agent_id, operation, conversation_id, message_data: (
                start_responses() if operation == "start_conversation" else None
            )
        )
        router.should_cleanup_on_client_stream_end.return_value = True
        context = MagicMock()
        context.is_active.return_value = False
        server = WxCCGatewayServer(router, request_queue_maxsize=1)

        def requests():
            yield self._session_start_request()
            yield self._custom_event_request()
            requested_second_buffered_input.set()
            yield self._custom_event_request()
            requested_third_buffered_input.set()
            yield self._custom_event_request()

        responses = server.ProcessCallerInput(requests(), context)
        first_response = next(responses)

        assert first_response.prompts[0].text == "Connected"
        assert requested_second_buffered_input.wait(0.5)
        assert requested_third_buffered_input.is_set() is False

        cancel_stream = context.add_callback.call_args.args[0]
        cancel_stream()
        allow_response_completion.set()

        assert list(responses) == []
        assert requested_third_buffered_input.is_set() is False
        assert [
            thread
            for thread in threading.enumerate()
            if id(thread) not in existing_thread_ids
            and thread.name
            in {"wxcc-request-reader", "wxcc-request-processor"}
        ] == []

    def test_bounded_response_backpressure_stops_on_stream_cancellation(self):
        router = MagicMock(spec=VirtualAgentRouter)
        attempted_third_response = threading.Event()
        completed_response_iterator = threading.Event()
        existing_thread_ids = {id(thread) for thread in threading.enumerate()}

        def start_responses():
            yield self._session_start_response()
            yield {
                **self._session_start_response(),
                "text": "Second buffered response",
            }
            attempted_third_response.set()
            yield {
                **self._session_start_response(),
                "text": "Third buffered response",
            }
            completed_response_iterator.set()

        router.route_request.side_effect = (
            lambda agent_id, operation, conversation_id, message_data: (
                start_responses() if operation == "start_conversation" else None
            )
        )
        router.should_cleanup_on_client_stream_end.return_value = True
        context = MagicMock()
        context.is_active.return_value = False
        server = WxCCGatewayServer(router, response_queue_maxsize=1)

        responses = server.ProcessCallerInput(
            iter([self._session_start_request()]), context
        )
        first_response = next(responses)

        assert first_response.prompts[0].text == "Connected"
        assert attempted_third_response.wait(0.5)
        assert completed_response_iterator.is_set() is False

        cancel_stream = context.add_callback.call_args.args[0]
        cancel_stream()

        assert list(responses) == []
        assert completed_response_iterator.is_set() is False
        assert [
            thread
            for thread in threading.enumerate()
            if id(thread) not in existing_thread_ids
            and thread.name
            in {"wxcc-request-reader", "wxcc-request-processor"}
        ] == []

    @pytest.mark.parametrize(
        ("argument", "message"),
        [
            ({"request_queue_maxsize": 0}, "request_queue_maxsize"),
            ({"response_queue_maxsize": 0}, "response_queue_maxsize"),
        ],
    )
    def test_stream_queue_sizes_must_be_positive(self, argument, message):
        with pytest.raises(ValueError, match=message):
            WxCCGatewayServer(
                MagicMock(spec=VirtualAgentRouter),
                **argument,
            )

    def test_opted_in_connector_survives_half_close_and_reconnection(self):
        router = MagicMock(spec=VirtualAgentRouter)
        router.route_request.side_effect = [self._session_start_response(), None]
        router.should_cleanup_on_client_stream_end.return_value = True
        context = MagicMock()
        context.is_active.return_value = True
        server = WxCCGatewayServer(router)

        first_responses = list(
            server.ProcessCallerInput(iter([self._session_start_request()]), context)
        )
        second_responses = list(
            server.ProcessCallerInput(iter([self._custom_event_request()]), context)
        )

        assert len(first_responses) == 1
        assert second_responses == []
        assert "stream-end-conv" in server.conversations
        assert (
            server.conversations["stream-end-conv"]._async_response_sink
            is None
        )
        start_calls = [
            call
            for call in router.route_request.call_args_list
            if len(call.args) > 1 and call.args[1] == "start_conversation"
        ]
        assert len(start_calls) == 1
        end_calls = [
            call
            for call in router.route_request.call_args_list
            if len(call.args) > 1 and call.args[1] == "end_conversation"
        ]
        assert end_calls == []

    def test_reconnection_rejects_virtual_agent_mismatch(self):
        router = MagicMock(spec=VirtualAgentRouter)
        router.route_request.side_effect = [self._session_start_response()]
        router.should_cleanup_on_client_stream_end.return_value = True
        first_context = MagicMock()
        first_context.is_active.return_value = True
        second_context = MagicMock()
        second_context.is_active.return_value = True
        server = WxCCGatewayServer(router)

        first_responses = list(
            server.ProcessCallerInput(
                iter([self._session_start_request()]), first_context
            )
        )
        mismatched_request = VoiceVARequest(
            conversation_id="stream-end-conv",
            virtual_agent_id="Different Agent",
            event_input=EventInput(
                event_type=EventInput.EventType.CUSTOM_EVENT,
                name="continue_call",
            ),
        )
        second_responses = list(
            server.ProcessCallerInput(iter([mismatched_request]), second_context)
        )

        assert len(first_responses) == 1
        assert second_responses == []
        second_context.set_code.assert_called_once_with(
            grpc.StatusCode.INVALID_ARGUMENT
        )
        assert server.conversations["stream-end-conv"].virtual_agent_id == (
            "GECX Agent"
        )
        start_calls = [
            call
            for call in router.route_request.call_args_list
            if len(call.args) > 1 and call.args[1] == "start_conversation"
        ]
        assert len(start_calls) == 1

    def test_opted_in_connector_cleans_up_cancelled_stream(self):
        router = MagicMock(spec=VirtualAgentRouter)
        router.route_request.side_effect = [self._session_start_response(), None]
        router.should_cleanup_on_client_stream_end.return_value = True
        context = MagicMock()
        context.is_active.return_value = False
        server = WxCCGatewayServer(router)

        responses = list(
            server.ProcessCallerInput(iter([self._session_start_request()]), context)
        )

        assert len(responses) == 1
        router.should_cleanup_on_client_stream_end.assert_called_with("GECX Agent")
        router.route_request.assert_any_call(
            "GECX Agent",
            "end_conversation",
            "stream-end-conv",
            {
                "conversation_id": "stream-end-conv",
                "virtual_agent_id": "GECX Agent",
                "input_type": "conversation_end",
                "termination_reason": "client_cancelled",
            },
        )
        assert "stream-end-conv" not in server.conversations

    def test_opted_in_connector_cleans_up_request_stream_error(self):
        router = MagicMock(spec=VirtualAgentRouter)
        router.route_request.side_effect = [self._session_start_response(), None]
        router.should_cleanup_on_client_stream_end.return_value = True
        context = MagicMock()
        context.is_active.return_value = True
        server = WxCCGatewayServer(router)

        def failing_requests():
            yield self._session_start_request()
            raise RuntimeError("request stream failed")

        responses = list(server.ProcessCallerInput(failing_requests(), context))

        assert len(responses) == 1
        router.route_request.assert_any_call(
            "GECX Agent",
            "end_conversation",
            "stream-end-conv",
            {
                "conversation_id": "stream-end-conv",
                "virtual_agent_id": "GECX Agent",
                "input_type": "conversation_end",
                "termination_reason": "stream_error",
            },
        )
        assert "stream-end-conv" not in server.conversations

    def test_default_connector_behavior_keeps_conversation_for_reconnection(self):
        router = MagicMock(spec=VirtualAgentRouter)
        router.route_request.return_value = self._session_start_response()
        router.should_cleanup_on_client_stream_end.return_value = False
        context = MagicMock()
        context.is_active.return_value = True
        server = WxCCGatewayServer(router)

        responses = list(
            server.ProcessCallerInput(iter([self._session_start_request()]), context)
        )

        assert len(responses) == 1
        assert "stream-end-conv" in server.conversations
        end_calls = [
            call
            for call in router.route_request.call_args_list
            if len(call.args) > 1 and call.args[1] == "end_conversation"
        ]
        assert end_calls == []
