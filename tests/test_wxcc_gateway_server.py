"""
Tests for the WxCC Gateway Server.

This module tests the gateway server's ability to handle both single responses
and generator responses from connectors, as well as proper audio input processing.
"""

import pytest
from unittest.mock import MagicMock, patch, Mock
from typing import Iterator, Dict, Any

from src.core.wxcc_gateway_server import ConversationProcessor
from src.core.virtual_agent_router import VirtualAgentRouter


class TestConversationProcessor:
    """Test the ConversationProcessor class."""

    @pytest.fixture
    def mock_router(self):
        """Create a mock router for testing."""
        router = MagicMock(spec=VirtualAgentRouter)
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
                "audio_data": b"test_audio_bytes"
            }
        )

        # Verify response was processed
        assert len(responses) == 1
        assert responses[0].prompts[0].text == "Hello, how can I help you?"
        assert responses[0].prompts[0].audio_content == b"audio_response_bytes"

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

    def test_process_audio_input_with_transfer_to_agent_event(self, processor, mock_router, mock_audio_input):
        """Test processing audio input with TRANSFER_TO_AGENT event from connector."""
        # Mock connector returning transfer response
        mock_response = {
            "message_type": "transfer",
            "text": "Let me transfer you to a human agent.",
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
        assert response.prompts[0].text == "Let me transfer you to a human agent."
        
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

        # Verify all responses were processed (None becomes valid responses)
        assert len(responses) == 3
        
        # First response should be a valid response (None becomes silence response)
        assert len(responses[0].prompts) == 0  # Silence response has no prompts
        
        # Second response should have content
        assert responses[1].prompts[0].text == "Valid response"
        
        # Third response should also be a valid response (None becomes silence response)
        assert len(responses[2].prompts) == 0  # Silence response has no prompts

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
