"""
Unit tests for the AWS Lex connector.

This module tests the AWSLexConnector class functionality including:
- Initialization and configuration
- AWS client setup
- Bot discovery and management
- Conversation lifecycle
- Message handling (audio, text, DTMF, events)
- Error handling and fallbacks
"""

import pytest
from unittest.mock import MagicMock, patch, Mock, call
import boto3
from botocore.exceptions import ClientError
import logging
from typing import Dict, Any

from src.connectors.aws_lex_connector import AWSLexConnector


class TestAWSLexConnector:
    """Test suite for AWSLexConnector."""

    @pytest.fixture
    def mock_config(self):
        """Provide a mock configuration for testing."""
        return {
            "region_name": "us-east-1",
            "aws_access_key_id": "test_key",
            "aws_secret_access_key": "test_secret",
            "bot_alias_id": "TESTALIAS"
        }

    @pytest.fixture
    def mock_config_no_creds(self):
        """Provide a mock configuration without explicit credentials."""
        return {
            "region_name": "us-east-1",
            "bot_alias_id": "TESTALIAS"
        }

    @pytest.fixture
    def mock_lex_client(self):
        """Provide a mock Lex client."""
        mock_client = MagicMock()
        mock_client.list_bots.return_value = {
            "botSummaries": [
                {"botId": "bot123", "botName": "TestBot"},
                {"botId": "bot456", "botName": "AnotherBot"}
            ]
        }
        return mock_client

    @pytest.fixture
    def mock_lex_runtime(self):
        """Provide a mock Lex runtime client."""
        mock_runtime = MagicMock()
        return mock_runtime

    @pytest.fixture
    def mock_session(self):
        """Provide a mock boto3 session."""
        mock_session = MagicMock()
        mock_session.client.side_effect = lambda service: {
            'lexv2-models': MagicMock(),
            'lexv2-runtime': MagicMock()
        }[service]
        return mock_session

    @pytest.fixture
    def connector(self, mock_config):
        """Provide a configured connector instance for testing."""
        with patch('boto3.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session.client.side_effect = lambda service: {
                'lexv2-models': MagicMock(),
                'lexv2-runtime': MagicMock()
            }[service]
            mock_session_class.return_value = mock_session
            
            connector = AWSLexConnector(mock_config)
            connector.logger = MagicMock()
            return connector

    def test_init_with_explicit_credentials(self, mock_config):
        """Test connector initialization with explicit AWS credentials."""
        with patch('boto3.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session.client.side_effect = lambda service: {
                'lexv2-models': MagicMock(),
                'lexv2-runtime': MagicMock()
            }[service]
            mock_session_class.return_value = mock_session
            
            connector = AWSLexConnector(mock_config)
            
            assert connector.region_name == "us-east-1"
            assert connector.aws_access_key_id == "test_key"
            assert connector.aws_secret_access_key == "test_secret"
            assert connector.bot_alias_id == "TESTALIAS"
            assert connector._available_bots is None
            assert connector._bot_name_to_id_map == {}
            assert connector._sessions == {}

    def test_init_without_credentials(self, mock_config_no_creds):
        """Test connector initialization without explicit AWS credentials."""
        with patch('boto3.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session.client.side_effect = lambda service: {
                'lexv2-models': MagicMock(),
                'lexv2-runtime': MagicMock()
            }[service]
            mock_session_class.return_value = mock_session
            
            connector = AWSLexConnector(mock_config_no_creds)
            
            assert connector.region_name == "us-east-1"
            assert connector.aws_access_key_id is None
            assert connector.aws_secret_access_key is None
            assert connector.bot_alias_id == "TESTALIAS"

    def test_init_missing_region_name(self):
        """Test connector initialization fails without region_name."""
        config = {"aws_access_key_id": "test_key"}
        
        with pytest.raises(ValueError, match="region_name is required"):
            AWSLexConnector(config)

    def test_init_aws_clients_success(self, mock_config):
        """Test successful AWS client initialization."""
        with patch('boto3.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session.client.side_effect = lambda service: {
                'lexv2-models': MagicMock(),
                'lexv2-runtime': MagicMock()
            }[service]
            mock_session_class.return_value = mock_session
            
            connector = AWSLexConnector(mock_config)
            
            assert hasattr(connector, 'lex_client')
            assert hasattr(connector, 'lex_runtime')

    def test_init_aws_clients_failure(self, mock_config):
        """Test AWS client initialization failure."""
        with patch('boto3.Session') as mock_session_class:
            mock_session_class.side_effect = Exception("AWS connection failed")
            
            with pytest.raises(Exception, match="AWS connection failed"):
                AWSLexConnector(mock_config)

    def test_get_available_agents_success(self, connector, mock_lex_client):
        """Test successful retrieval of available agents."""
        connector.lex_client = mock_lex_client
        
        agents = connector.get_available_agents()
        
        expected_agents = [
            "aws_lex_connector: TestBot",
            "aws_lex_connector: AnotherBot"
        ]
        assert agents == expected_agents
        assert connector._bot_name_to_id_map["aws_lex_connector: TestBot"] == "bot123"
        assert connector._bot_name_to_id_map["aws_lex_connector: AnotherBot"] == "bot456"

    def test_get_available_agents_client_error(self, connector):
        """Test handling of AWS client errors when getting agents."""
        mock_client = MagicMock()
        mock_client.list_bots.side_effect = ClientError(
            {'Error': {'Code': 'AccessDenied', 'Message': 'Access denied'}},
            'ListBots'
        )
        connector.lex_client = mock_client
        
        agents = connector.get_available_agents()
        
        assert agents == []
        connector.logger.error.assert_called()

    def test_get_available_agents_unexpected_error(self, connector):
        """Test handling of unexpected errors when getting agents."""
        mock_client = MagicMock()
        mock_client.list_bots.side_effect = Exception("Unexpected error")
        connector.lex_client = mock_client
        
        agents = connector.get_available_agents()
        
        assert agents == []
        connector.logger.error.assert_called()

    def test_get_available_agents_cached(self, connector, mock_lex_client):
        """Test that available agents are cached after first call."""
        connector.lex_client = mock_lex_client
        
        # First call should populate cache
        agents1 = connector.get_available_agents()
        # Second call should use cache
        agents2 = connector.get_available_agents()
        
        assert agents1 == agents2
        # Should only call list_bots once
        mock_lex_client.list_bots.assert_called_once()

    def test_start_conversation_success(self, connector, mock_lex_runtime):
        """Test successful conversation start."""
        # Setup bot mapping
        connector._bot_name_to_id_map = {"aws_lex_connector: TestBot": "bot123"}
        
        # Mock successful Lex response
        mock_audio_stream = MagicMock()
        mock_audio_stream.read.return_value = b"audio_data"
        mock_audio_stream.close.return_value = None
        
        mock_response = {
            'audioStream': mock_audio_stream
        }
        mock_lex_runtime.recognize_utterance.return_value = mock_response
        
        connector.lex_runtime = mock_lex_runtime
        
        # Mock audio conversion
        with patch('src.connectors.aws_lex_connector.convert_aws_lex_audio_to_wxcc') as mock_convert:
            mock_convert.return_value = (b"converted_audio", "audio/wav")
            
            response = connector.start_conversation("conv123", {
                "virtual_agent_id": "aws_lex_connector: TestBot"
            })
            
            assert response["conversation_id"] == "conv123"
            assert response["message_type"] == "welcome"
            assert "TestBot" in response["text"]
            assert response["audio_content"] == b"converted_audio"
            assert response["barge_in_enabled"] is True

    def test_start_conversation_bot_not_found(self, connector):
        """Test conversation start with unknown bot."""
        connector._bot_name_to_id_map = {}
        
        response = connector.start_conversation("conv123", {
            "virtual_agent_id": "aws_lex_connector: UnknownBot"
        })
        
        assert response["message_type"] == "error"
        assert "having trouble starting our conversation" in response["text"]

    def test_start_conversation_lex_api_error(self, connector, mock_lex_runtime):
        """Test conversation start with Lex API error."""
        connector._bot_name_to_id_map = {"aws_lex_connector: TestBot": "bot123"}
        
        mock_lex_runtime.recognize_utterance.side_effect = ClientError(
            {'Error': {'Code': 'BotNotFound', 'Message': 'Bot not found'}},
            'RecognizeUtterance'
        )
        connector.lex_runtime = mock_lex_runtime
        
        response = connector.start_conversation("conv123", {
            "virtual_agent_id": "aws_lex_connector: TestBot"
        })
        
        assert response["message_type"] == "welcome"
        assert "TestBot" in response["text"]
        connector.logger.error.assert_called()

    def test_start_conversation_no_audio_response(self, connector, mock_lex_runtime):
        """Test conversation start with no audio response from Lex."""
        connector._bot_name_to_id_map = {"aws_lex_connector: TestBot": "bot123"}
        
        # Mock response without audio stream
        mock_response = {}
        mock_lex_runtime.recognize_utterance.return_value = mock_response
        connector.lex_runtime = mock_lex_runtime
        
        response = connector.start_conversation("conv123", {
            "virtual_agent_id": "aws_lex_connector: TestBot"
        })
        
        assert response["message_type"] == "welcome"
        assert response["audio_content"] == b""
        assert response["barge_in_enabled"] is False

    def test_send_message_conversation_start(self, connector):
        """Test handling of conversation start message."""
        # Need to set up a session first since send_message checks for active sessions
        connector._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {
            "input_type": "conversation_start",
            "conversation_id": "conv123"
        }
        
        response = connector.send_message("conv123", message_data)
        
        assert response["message_type"] == "silence"
        assert response["conversation_id"] == "conv123"

    def test_send_message_dtmf_transfer(self, connector):
        """Test handling of DTMF transfer request."""
        connector._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {
            "input_type": "dtmf",
            "dtmf_data": {"dtmf_events": [5]},
            "conversation_id": "conv123"
        }
        
        response = connector.send_message("conv123", message_data)
        
        assert response["message_type"] == "transfer"
        assert "Transferring" in response["text"]
        assert "TestBot" in response["text"]

    def test_send_message_dtmf_goodbye(self, connector):
        """Test handling of DTMF goodbye request."""
        connector._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {
            "input_type": "dtmf",
            "dtmf_data": {"dtmf_events": [6]},
            "conversation_id": "conv123"
        }
        
        response = connector.send_message("conv123", message_data)
        
        assert response["message_type"] == "goodbye"
        assert "Goodbye" in response["text"]
        assert "TestBot" in response["text"]

    def test_send_message_dtmf_other_digits(self, connector):
        """Test handling of other DTMF digits."""
        connector._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {
            "input_type": "dtmf",
            "dtmf_data": {"dtmf_events": [1, 2, 3]},
            "conversation_id": "conv123"
        }
        
        with patch.object(connector, '_send_text_to_lex') as mock_send_text:
            mock_send_text.return_value = {"message_type": "silence"}
            
            response = connector.send_message("conv123", message_data)
            
            mock_send_text.assert_called_once_with("conv123", "DTMF 123")

    def test_send_message_audio_input(self, connector, mock_lex_runtime):
        """Test handling of audio input."""
        connector._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {
            "input_type": "audio",
            "audio_data": b"input_audio",
            "conversation_id": "conv123"
        }
        
        response = connector.send_message("conv123", message_data)
        
        # Now that we're just buffering audio, expect a silence response
        assert response["message_type"] == "silence"
        assert "Audio received and buffered" in response["text"]
        assert response["barge_in_enabled"] is True
        assert response["response_type"] == "silence"

    def test_send_message_no_session(self, connector):
        """Test handling of message with no active session."""
        message_data = {
            "input_type": "audio",
            "audio_data": b"input_audio",
            "conversation_id": "conv123"
        }
        
        response = connector.send_message("conv123", message_data)
        
        assert response["message_type"] == "error"
        assert "No active conversation" in response["text"]

    def test_send_message_event(self, connector):
        """Test handling of event input."""
        connector._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {
            "input_type": "event",
            "event_data": {"name": "test_event"},
            "conversation_id": "conv123"
        }
        
        response = connector.send_message("conv123", message_data)
        
        assert response["message_type"] == "silence"
        assert response["conversation_id"] == "conv123"

    def test_send_message_unrecognized_input(self, connector):
        """Test handling of unrecognized input type."""
        connector._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {
            "input_type": "unknown_type",
            "conversation_id": "conv123"
        }
        
        response = connector.send_message("conv123", message_data)
        
        assert response["message_type"] == "silence"
        assert response["conversation_id"] == "conv123"

    def test_end_conversation_success(self, connector):
        """Test successful conversation ending."""
        connector._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        connector.end_conversation("conv123")
        
        assert "conv123" not in connector._sessions
        connector.logger.info.assert_called()

    def test_end_conversation_no_session(self, connector):
        """Test ending non-existent conversation."""
        connector.end_conversation("nonexistent")
        
        connector.logger.warning.assert_called()

    def test_end_conversation_with_message_data(self, connector):
        """Test ending conversation with message data."""
        connector._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {"generate_response": True}
        connector.end_conversation("conv123", message_data)
        
        assert "conv123" not in connector._sessions

    def test_convert_wxcc_to_vendor(self, connector):
        """Test conversion from WxCC to vendor format."""
        wxcc_data = {"test": "data"}
        result = connector.convert_wxcc_to_vendor(wxcc_data)
        
        assert result == wxcc_data

    def test_convert_vendor_to_wxcc(self, connector):
        """Test conversion from vendor to WxCC format."""
        vendor_data = {"test": "data"}
        result = connector.convert_vendor_to_wxcc(vendor_data)
        
        assert result == vendor_data

    def test_refresh_bot_cache(self, connector):
        """Test refreshing the bot cache."""
        connector._available_bots = ["cached_bot"]
        connector._bot_name_to_id_map = {"cached": "bot"}
        
        with patch.object(connector, 'get_available_agents') as mock_get_agents:
            connector._refresh_bot_cache()
            
            assert connector._available_bots is None
            assert connector._bot_name_to_id_map == {}
            mock_get_agents.assert_called_once()

    def test_create_response(self, connector):
        """Test creating standardized responses."""
        response = connector.create_response(
            conversation_id="conv123",
            message_type="test",
            text="Test message",
            audio_content=b"audio",
            barge_in_enabled=True,
            extra_param="extra"
        )
        
        assert response["conversation_id"] == "conv123"
        assert response["message_type"] == "test"
        assert response["text"] == "Test message"
        assert response["audio_content"] == b"audio"
        assert response["barge_in_enabled"] is True
        assert response["extra_param"] == "extra"

    def test_extract_audio_data_bytes(self, connector):
        """Test audio data extraction from bytes."""
        audio_bytes = b"test_audio"
        result = connector.extract_audio_data(audio_bytes, "conv123")
        
        assert result == audio_bytes

    def test_extract_audio_data_dict(self, connector):
        """Test audio data extraction from dictionary."""
        audio_dict = {"audio_data": b"test_audio"}
        result = connector.extract_audio_data(audio_dict, "conv123")
        
        assert result == b"test_audio"

    def test_extract_audio_data_string(self, connector):
        """Test audio data extraction from string."""
        import base64
        audio_string = base64.b64encode(b"test_audio").decode('utf-8')
        result = connector.extract_audio_data(audio_string, "conv123")
        
        assert result == b"test_audio"

    def test_extract_audio_data_none(self, connector):
        """Test audio data extraction with None input."""
        result = connector.extract_audio_data(None, "conv123")
        
        assert result is None

    def test_handle_conversation_start(self, connector):
        """Test conversation start event handling."""
        message_data = {"event": "start"}
        response = connector.handle_conversation_start("conv123", message_data)
        
        assert response["message_type"] == "silence"
        assert response["conversation_id"] == "conv123"

    def test_handle_event(self, connector):
        """Test event handling."""
        message_data = {"event_data": {"name": "test_event"}}
        response = connector.handle_event("conv123", message_data)
        
        assert response["message_type"] == "silence"
        assert response["conversation_id"] == "conv123"

    def test_handle_audio_input(self, connector):
        """Test audio input handling."""
        message_data = {"audio": "data"}
        response = connector.handle_audio_input("conv123", message_data)
        
        assert response["message_type"] == "silence"
        assert response["conversation_id"] == "conv123"

    def test_handle_unrecognized_input(self, connector):
        """Test unrecognized input handling."""
        message_data = {"input_type": "unknown"}
        response = connector.handle_unrecognized_input("conv123", message_data)
        
        assert response["message_type"] == "silence"
        assert response["conversation_id"] == "conv123"

    def test_audio_buffering_initialization(self, mock_boto3_session, mock_lex_client, mock_lex_runtime):
        """Test that audio buffering is properly initialized."""
        config = {
            "region_name": "us-east-1",
            "audio_recording": {
                "output_dir": "test_logs",
                "silence_threshold": 2500,
                "silence_duration": 1.5,
                "quiet_threshold": 15
            }
        }
        
        connector = AWSLexConnector(config)
        
        # Check that audio buffering is always enabled
        assert connector.audio_buffering_config == config["audio_recording"]
        assert connector.audio_buffers == {}

    def test_audio_buffering_always_enabled(self, mock_boto3_session, mock_lex_client, mock_lex_runtime):
        """Test that audio buffering is always enabled for AWS Lex connector."""
        config = {"region_name": "us-east-1"}
        
        connector = AWSLexConnector(config)
        
        # Check that audio buffering is always enabled (no config needed)
        assert connector.audio_buffering_config == {}
        assert connector.audio_buffers == {}

    def test_audio_buffer_creation(self, mock_boto3_session, mock_lex_client, mock_lex_runtime):
        """Test that audio buffer is created when needed."""
        config = {
            "region_name": "us-east-1",
            "audio_recording": {
                "output_dir": "test_logs",
                "silence_threshold": 3000,
                "silence_duration": 2.0,
                "quiet_threshold": 20
            }
        }
        
        connector = AWSLexConnector(config)
        
        # Initially no buffers
        assert len(connector.audio_buffers) == 0
        
        # Create a buffer
        connector._init_audio_buffer("test_conv_123")
        
        # Should have one buffer now
        assert len(connector.audio_buffers) == 1
        assert "test_conv_123" in connector.audio_buffers
        
        # Check buffer properties
        buffer = connector.audio_buffers["test_conv_123"]
        assert buffer.conversation_id == "test_conv_123"
        assert buffer.buffer_only is True
        assert buffer.silence_threshold == 3000
        assert buffer.silence_duration == 2.0
        assert buffer.quiet_threshold == 20


if __name__ == "__main__":
    pytest.main([__file__])
