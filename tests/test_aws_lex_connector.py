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
            "bot_alias_id": "TESTALIAS",
            "barge_in_enabled": False
        }

    @pytest.fixture
    def mock_config_no_creds(self):
        """Provide a mock configuration without explicit credentials."""
        return {
            "region_name": "us-east-1",
            "bot_alias_id": "TESTALIAS",
            "barge_in_enabled": False
        }

    @pytest.fixture
    def mock_config_barge_in_enabled(self):
        """Provide a mock configuration with barge-in enabled."""
        return {
            "region_name": "us-east-1",
            "aws_access_key_id": "test_key",
            "aws_secret_access_key": "test_secret",
            "bot_alias_id": "TESTALIAS",
            "barge_in_enabled": True
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
            connector.session_manager.logger = MagicMock()
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
            
            assert connector.config_manager.get_region_name() == "us-east-1"
            assert connector.config_manager.is_barge_in_enabled() is False

    def test_init_with_barge_in_enabled(self, mock_config_barge_in_enabled):
        """Test connector initialization with barge-in enabled."""
        with patch('boto3.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session.client.side_effect = lambda service: {
                'lexv2-models': MagicMock(),
                'lexv2-runtime': MagicMock()
            }[service]
            mock_session_class.return_value = mock_session
            
            connector = AWSLexConnector(mock_config_barge_in_enabled)
            
            assert connector.config_manager.get_region_name() == "us-east-1"
            assert connector.config_manager.is_barge_in_enabled() is True
            assert connector.config_manager.get_aws_credentials()["aws_access_key_id"] == "test_key"
            assert connector.config_manager.get_aws_credentials()["aws_secret_access_key"] == "test_secret"
            assert connector.config_manager.get_bot_alias_id() == "TESTALIAS"
            assert connector.session_manager._available_bots is None
            assert connector.session_manager._bot_name_to_id_map == {}
            assert connector.session_manager._sessions == {}

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
            
            assert connector.config_manager.get_region_name() == "us-east-1"
            assert connector.config_manager.get_aws_credentials()["aws_access_key_id"] is None
            assert connector.config_manager.get_aws_credentials()["aws_secret_access_key"] is None
            assert connector.config_manager.get_bot_alias_id() == "TESTALIAS"

    def test_init_missing_region_name(self):
        """Test connector initialization fails without region_name."""
        config = {"aws_access_key_id": "test_key"}
        
        with pytest.raises(ValueError, match="Required configuration key 'region_name' is missing"):
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
        assert connector.session_manager._bot_name_to_id_map["aws_lex_connector: TestBot"] == "bot123"
        assert connector.session_manager._bot_name_to_id_map["aws_lex_connector: AnotherBot"] == "bot456"

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
        connector.session_manager.logger.error.assert_called()

    def test_get_available_agents_unexpected_error(self, connector):
        """Test handling of unexpected errors when getting agents."""
        mock_client = MagicMock()
        mock_client.list_bots.side_effect = Exception("Unexpected error")
        connector.lex_client = mock_client
        
        agents = connector.get_available_agents()
        
        assert agents == []
        connector.session_manager.logger.error.assert_called()

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
        connector.session_manager._bot_name_to_id_map = {"aws_lex_connector: TestBot": "bot123"}
        
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
        with patch('src.connectors.aws_lex_connector.AWSLexAudioProcessor.convert_lex_audio_to_wxcc_format') as mock_convert:
            mock_convert.return_value = (b"converted_audio", "audio/wav")
            
            response = connector.start_conversation("conv123", {
                "virtual_agent_id": "aws_lex_connector: TestBot"
            })
            
            assert response["conversation_id"] == "conv123"
            assert response["message_type"] == "welcome"
            assert "TestBot" in response["text"]
            assert response["audio_content"] == b"converted_audio"
            assert response["barge_in_enabled"] is False

    def test_start_conversation_with_barge_in_enabled(self, mock_config_barge_in_enabled):
        """Test conversation start with barge-in enabled configuration."""
        with patch('boto3.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session.client.side_effect = lambda service: {
                'lexv2-models': MagicMock(),
                'lexv2-runtime': MagicMock()
            }[service]
            mock_session_class.return_value = mock_session
            
            connector = AWSLexConnector(mock_config_barge_in_enabled)
            connector.logger = MagicMock()
            connector.session_manager.logger = MagicMock()
            
            # Mock the bot discovery
            connector.session_manager._bot_name_to_id_map = {"aws_lex_connector: TestBot": "bot123"}
            
            # Mock the Lex response
            mock_response = MagicMock()
            mock_response.audioStream = b"test_audio"
            mock_response.contentType = "audio/pcm"
            
            connector.lex_runtime = MagicMock()
            connector.lex_runtime.recognize_utterance.return_value = mock_response
            
            # Mock audio conversion
            connector.audio_processor = MagicMock()
            connector.audio_processor.convert_lex_audio_to_wxcc_format.return_value = (b"converted_audio", "audio/wav")
            
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
        connector.session_manager._bot_name_to_id_map = {"aws_lex_connector: TestBot": "bot123"}
        
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
        connector.session_manager._bot_name_to_id_map = {"aws_lex_connector: TestBot": "bot123"}
        
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
        connector.session_manager._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {
            "input_type": "conversation_start",
            "conversation_id": "conv123"
        }
        
        response = list(connector.send_message("conv123", message_data))
        assert len(response) == 1
        assert response[0]["message_type"] == "silence"

    def test_send_message_dtmf_transfer(self, connector):
        """Test handling of DTMF transfer request."""
        connector.session_manager._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {
            "input_type": "dtmf",
            "dtmf_data": {"dtmf_events": [5]},
            "conversation_id": "conv123"
        }
        
        response = list(connector.send_message("conv123", message_data))
        assert len(response) == 1
        assert response[0]["message_type"] == "transfer"

    def test_send_message_dtmf_goodbye(self, connector):
        """Test handling of DTMF goodbye request."""
        connector.session_manager._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {
            "input_type": "dtmf",
            "dtmf_data": {"dtmf_events": [6]},
            "conversation_id": "conv123"
        }
        
        response = list(connector.send_message("conv123", message_data))
        assert len(response) == 1
        assert response[0]["message_type"] == "goodbye"

    def test_send_message_dtmf_other_digits(self, connector):
        """Test handling of other DTMF digits."""
        connector.session_manager._sessions["conv123"] = {
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
            
            response = list(connector.send_message("conv123", message_data))
            assert len(response) == 1
            mock_send_text.assert_called_once_with("conv123", "DTMF 123")

    def test_send_message_audio_input(self, connector, mock_lex_runtime):
        """Test handling of audio input."""
        connector.session_manager._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {
            "input_type": "audio",
            "audio_data": b"input_audio",
            "conversation_id": "conv123"
        }
        
        # First call should send START_OF_INPUT event
        responses = list(connector.send_message("conv123", message_data))
        assert len(responses) == 1
        assert responses[0]["message_type"] == "silence"
        assert responses[0]["text"] == ""
        assert "output_events" in responses[0]
        assert len(responses[0]["output_events"]) == 1
        assert responses[0]["output_events"][0]["event_type"] == "START_OF_INPUT"
        assert responses[0]["output_events"][0]["name"] == ""  # Empty name for START_OF_INPUT
        assert responses[0]["barge_in_enabled"] is True
        assert responses[0]["response_type"] == "silence"
        
        # Second call should return no response since no silence detected
        # (audio is just being buffered)
        responses = list(connector.send_message("conv123", message_data))
        assert len(responses) == 0  # No response when just buffering audio

    def test_send_message_no_session(self, connector):
        """Test handling of message with no active session."""
        message_data = {
            "input_type": "audio",
            "audio_data": b"input_audio",
            "conversation_id": "conv123"
        }
        
        response = list(connector.send_message("conv123", message_data))
        assert len(response) == 1
        assert response[0]["message_type"] == "error"

    def test_send_message_event(self, connector):
        """Test handling of event input."""
        connector.session_manager._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {
            "input_type": "event",
            "event_data": {"name": "test_event"},
            "conversation_id": "conv123"
        }
        
        response = list(connector.send_message("conv123", message_data))
        assert len(response) == 1
        assert response[0]["message_type"] == "silence"

    def test_send_message_unrecognized_input(self, connector):
        """Test handling of unrecognized input type."""
        connector.session_manager._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {
            "input_type": "unknown_type",
            "conversation_id": "conv123"
        }
        
        response = list(connector.send_message("conv123", message_data))
        assert len(response) == 1
        assert response[0]["message_type"] == "silence"

    def test_end_conversation_success(self, connector):
        """Test successful conversation ending."""
        connector.session_manager._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        connector.end_conversation("conv123")
        
        assert "conv123" not in connector.session_manager._sessions
        connector.logger.info.assert_called()

    def test_end_conversation_no_session(self, connector):
        """Test ending non-existent conversation."""
        connector.end_conversation("nonexistent")
        
        connector.session_manager.logger.warning.assert_called()

    def test_end_conversation_with_message_data(self, connector):
        """Test ending conversation with message data."""
        connector.session_manager._sessions["conv123"] = {
            "bot_name": "TestBot",
            "session_id": "session123",
            "actual_bot_id": "bot123"
        }
        
        message_data = {"generate_response": True}
        connector.end_conversation("conv123", message_data)
        
        assert "conv123" not in connector.session_manager._sessions

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
        connector.session_manager._available_bots = ["cached_bot"]
        connector.session_manager._bot_name_to_id_map = {"cached": "bot"}
        
        with patch.object(connector, 'get_available_agents') as mock_get_agents:
            connector._refresh_bot_cache()
            
            assert connector.session_manager._available_bots is None
            assert connector.session_manager._bot_name_to_id_map == {}
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
            "audio_buffering": {
                "silence_threshold": 2500,
                "silence_duration": 1.5,
                "quiet_threshold": 15
            }
        }

        connector = AWSLexConnector(config)

        # Check that audio buffering is properly configured
        assert connector.audio_processor.audio_buffering_config == config["audio_buffering"]
        assert connector.audio_processor.audio_buffers == {}

    def test_audio_buffering_always_enabled(self, mock_boto3_session, mock_lex_client, mock_lex_runtime):
        """Test that audio buffering is always enabled for AWS Lex connector."""
        config = {"region_name": "us-east-1"}
        
        connector = AWSLexConnector(config)
        
        # Check that audio buffering uses default values when no config provided
        assert connector.audio_processor.audio_buffering_config == {
            "silence_threshold": 2000,
            "silence_duration": 2.5,
            "quiet_threshold": 20
        }
        assert connector.audio_processor.audio_buffers == {}

    def test_audio_buffer_creation(self, connector):
        """Test that audio buffers are created correctly."""
        # Test buffer initialization
        connector.audio_processor.init_audio_buffer("test_conv_123")
        
        assert "test_conv_123" in connector.audio_processor.audio_buffers
        buffer = connector.audio_processor.audio_buffers["test_conv_123"]
        
        assert buffer.conversation_id == "test_conv_123"
        assert buffer.sample_rate == 8000
        assert buffer.bit_depth == 8
        assert buffer.channels == 1
        assert buffer.encoding == "ulaw"

    def test_audio_conversion_integration(self, connector):
        """Test that audio conversion works correctly in the AWS Lex connector context."""
        # Create test PCM data (16kHz, 16-bit, mono)
        import struct
        import math
        
        # Generate a simple sine wave pattern for testing
        sample_rate = 16000
        duration = 0.1  # 100ms
        num_samples = int(sample_rate * duration)
        
        test_pcm_data = b""
        for i in range(num_samples):
            # Simple sine wave at 440 Hz
            sample = int(16384 * math.sin(2 * math.pi * 440 * i / sample_rate))
            test_pcm_data += struct.pack("<h", sample)
        
        # Test the audio conversion function that the connector uses
        from src.utils.audio_utils import convert_aws_lex_audio_to_wxcc
        
        wav_audio, content_type = convert_aws_lex_audio_to_wxcc(
            test_pcm_data,
            bit_depth=16
        )
        
        # Verify the conversion worked
        assert content_type == "audio/wav"
        assert len(wav_audio) > 0
        
        # Verify WAV header structure
        assert wav_audio.startswith(b'RIFF')
        assert b'WAVE' in wav_audio
        assert b'fmt ' in wav_audio
        assert b'data' in wav_audio
        
        # Verify WxCC-compatible format
        sample_rate_wav = struct.unpack('<I', wav_audio[24:28])[0]
        bit_depth_wav = struct.unpack('<H', wav_audio[34:36])[0]
        channels_wav = struct.unpack('<H', wav_audio[22:24])[0]
        format_code = struct.unpack('<H', wav_audio[20:22])[0]
        
        assert sample_rate_wav == 8000, f"Sample rate must be 8000 Hz, got {sample_rate_wav}"
        assert bit_depth_wav == 8, f"Bit depth must be 8, got {bit_depth_wav}"
        assert channels_wav == 1, f"Channels must be 1, got {channels_wav}"
        assert format_code == 7, f"Encoding must be u-law (7), got {format_code}"
        
        # Verify the connector can use this converted audio
        response = connector.create_response(
            conversation_id="test_conv_456",
            message_type="welcome",
            text="Test audio response",
            audio_content=wav_audio,
            barge_in_enabled=True,
            response_type="final"
        )
        
        assert response["audio_content"] == wav_audio
        assert response["text"] == "Test audio response"
        assert response["message_type"] == "welcome"

    def test_reset_conversation_for_next_input_success(self, connector):
        """Test successful reset of conversation state for next audio input cycle."""
        conversation_id = "test_conv_789"
        
        # Set up initial state - conversation has START_OF_INPUT tracking
        connector.session_manager.conversations_with_start_of_input.add(conversation_id)
        assert conversation_id in connector.session_manager.conversations_with_start_of_input
        
        # Call the reset method
        connector.session_manager.reset_conversation_for_next_input(conversation_id)
        
        # Verify conversation was removed from START_OF_INPUT tracking
        assert conversation_id not in connector.session_manager.conversations_with_start_of_input
        assert len(connector.session_manager.conversations_with_start_of_input) == 0

    def test_reset_conversation_for_next_input_not_tracked(self, connector):
        """Test reset when conversation is not in START_OF_INPUT tracking."""
        conversation_id = "test_conv_790"
        
        # Ensure conversation is not in tracking
        connector.session_manager.conversations_with_start_of_input.discard(conversation_id)
        assert conversation_id not in connector.session_manager.conversations_with_start_of_input
        
        # Call the reset method
        connector.session_manager.reset_conversation_for_next_input(conversation_id)
        
        # Verify conversation still not in tracking
        assert conversation_id not in connector.session_manager.conversations_with_start_of_input

    def test_reset_conversation_for_next_input_error_handling(self, connector):
        """Test that reset method handles errors gracefully."""
        conversation_id = "test_conv_791"
        
        # Set up initial state
        connector.session_manager.conversations_with_start_of_input.add(conversation_id)
        
        # Mock the logger to capture error calls
        connector.session_manager.logger.error = MagicMock()
        
        # Create a custom set-like object that raises an exception on remove
        class ExceptionRaisingSet(set):
            def remove(self, item):
                raise Exception("Test error")
        
        # Replace the set with our custom one
        original_set = connector.session_manager.conversations_with_start_of_input
        connector.session_manager.conversations_with_start_of_input = ExceptionRaisingSet([conversation_id])
        
        try:
            # Call the reset method - should not raise exception
            connector.session_manager.reset_conversation_for_next_input(conversation_id)
            
            # Verify error was logged
            connector.session_manager.logger.error.assert_called_with(
                f"Error resetting conversation {conversation_id} for next input: Test error"
            )
        finally:
            # Restore the original set
            connector.session_manager.conversations_with_start_of_input = original_set

    def test_multiple_audio_input_cycles_success(self, connector, mock_lex_runtime):
        """Test that multiple audio input cycles work correctly with reset functionality."""
        conversation_id = "test_conv_792"
        bot_id = "test_bot_123"
        session_id = "session_123"
        
        # Set up session
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        # Set up audio buffer
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        
        # Add some audio data to the buffer so it's not empty
        audio_buffer.add_audio_data(b"test_audio_data", encoding="ulaw")
        assert audio_buffer.get_buffer_size() > 0
        
        # Mock Lex response
        mock_audio_stream = MagicMock()
        mock_audio_stream.read.return_value = b"mock_audio_response"
        mock_audio_stream.close.return_value = None
        
        mock_response = {
            'audioStream': mock_audio_stream,
            'messages': 'gAAAAABk...',  # Mock encoded messages
            'inputTranscript': 'gAAAAABk...'  # Mock encoded transcript
        }
        
        # Mock the decode method to return test data
        with patch.object(connector.response_handler, '_decode_lex_response') as mock_decode:
            mock_decode.side_effect = [
                "What type of room would you like?",  # inputTranscript (called first)
                [{'content': 'What type of room would you like? king, queen, or deluxe?', 'contentType': 'PlainText'}],  # messages (called second)
                [{'intent': {'name': 'BookRoom', 'state': 'InProgress'}}],  # interpretations (called third)
                {'dialogAction': {'type': 'ElicitSlot'}, 'activeContexts': []}  # sessionState (called fourth)
            ]
            
            # Mock audio conversion
            with patch('src.utils.audio_utils.convert_aws_lex_audio_to_wxcc') as mock_convert:
                mock_convert.return_value = (b"converted_audio", "audio/wav")
                
                # Mock Lex runtime call
                with patch.object(connector.lex_runtime, 'recognize_utterance', return_value=mock_response):
                    
                    # First cycle: Send audio to Lex and get response
                    responses = list(connector._send_audio_to_lex(conversation_id))
                    
                    # Verify response was generated
                    assert len(responses) == 1
                    response = responses[0]
                    assert response["conversation_id"] == conversation_id
                    assert response["message_type"] == "response"
                    assert response["response_type"] == "final"
                    
                    # Verify conversation state was reset
                    assert conversation_id not in connector.session_manager.conversations_with_start_of_input
                    
                    # Verify audio buffer was reset
                    assert audio_buffer.get_buffer_size() == 0
                    
                    # Second cycle: Should be able to send START_OF_INPUT again
                    message_data = {"input_type": "audio", "audio_data": b"new_audio_input"}
                    
                    # Mock audio extraction
                    with patch.object(connector, 'extract_audio_data', return_value=b"new_audio_input"):
                        # Mock audio buffering
                        with patch.object(connector.audio_processor, 'process_audio_for_buffering', return_value=False):
                            responses = list(connector._handle_audio_input(conversation_id, message_data, bot_id, session_id, "TestBot"))
                            
                            # Should send START_OF_INPUT since conversation was reset
                            assert len(responses) == 1
                            start_response = responses[0]
                            assert "output_events" in start_response
                            assert len(start_response["output_events"]) == 1
                            assert start_response["output_events"][0]["event_type"] == "START_OF_INPUT"

    def test_reset_integration_with_dtmf_transfer(self, connector):
        """Test that conversation reset works correctly with DTMF transfer."""
        conversation_id = "test_conv_793"
        bot_id = "test_bot_123"
        session_id = "session_123"
        
        # Set up session
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        # Set up initial state
        connector.session_manager.conversations_with_start_of_input.add(conversation_id)
        
        # Create DTMF message with transfer code (5)
        message_data = {
            "input_type": "dtmf",
            "dtmf_data": {"dtmf_events": [5]}
        }
        
        # Process DTMF input
        response = connector._handle_dtmf_input(conversation_id, message_data, bot_id, session_id, "TestBot")
        
        # Verify transfer response
        assert response["message_type"] == "transfer"
        assert "output_events" in response
        assert response["output_events"][0]["event_type"] == "TRANSFER_TO_HUMAN"
        
        # Verify conversation state was reset
        assert conversation_id not in connector.session_manager.conversations_with_start_of_input

    def test_reset_integration_with_dtmf_goodbye(self, connector):
        """Test that conversation reset works correctly with DTMF goodbye."""
        
    def test_session_end_on_dialog_action_close(self, connector):
        """Test that SESSION_END event is sent when Lex returns dialog_action=Close."""
        conversation_id = "test_conv_session_end"
        bot_id = "test_bot_123"
        session_id = "session_123"
        
        # Set up session
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        # Set up audio buffer
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        audio_buffer.add_audio_data(b"test_audio_data", encoding="ulaw")
        
        # Mock Lex response with dialog_action=Close
        mock_response = {
            'interpretations': 'gAAAAABk...',  # Mock encoded interpretations
            'sessionState': 'gAAAAABk...',    # Mock encoded session state
            'messages': 'gAAAAABk...',        # Mock encoded messages
            'inputTranscript': 'gAAAAABk...'  # Mock encoded transcript
        }
        
        # Mock audio stream for the response (required for normal flow)
        mock_audio_stream = MagicMock()
        mock_audio_stream.read.return_value = b"mock_audio_response"
        mock_audio_stream.close.return_value = None
        mock_response['audioStream'] = mock_audio_stream
        
        # Mock the decode method to return test data
        with patch.object(connector.response_handler, '_decode_lex_response') as mock_decode:
            mock_decode.side_effect = [
                "Goodbye",  # inputTranscript (called first)
                [{'content': 'Goodbye message', 'contentType': 'PlainText'}],  # messages (called second)
                [{'intent': {'name': 'Goodbye', 'state': 'ReadyForFulfillment'}}],  # interpretations (called third)
                {'dialogAction': {'type': 'Close'}, 'activeContexts': []}  # sessionState (called fourth)
            ]
            
            # Mock audio conversion
            with patch('src.utils.audio_utils.convert_aws_lex_audio_to_wxcc') as mock_convert:
                mock_convert.return_value = (b"converted_audio", "audio/wav")
                
                # Mock Lex runtime call
                with patch.object(connector.lex_runtime, 'recognize_utterance', return_value=mock_response):
                    
                    # Process audio input
                    responses = list(connector._send_audio_to_lex(conversation_id))
                
                # Verify SESSION_END response was generated
                assert len(responses) == 1
                response = responses[0]
                assert response["conversation_id"] == conversation_id
                assert response["message_type"] == "session_end"
                assert response["text"] == "Thank you for calling. Have a great day!"
                assert response["response_type"] == "final"
                assert response["barge_in_enabled"] == False
                
                                # Verify SESSION_END output event
                assert "output_events" in response
                assert len(response["output_events"]) == 1
                event = response["output_events"][0]
                assert event["event_type"] == "SESSION_END"
                assert event["name"] == "lex_conversation_ended"
                assert event["metadata"]["reason"] == "lex_dialog_closed"
                assert event["metadata"]["bot_name"] == "TestBot"
                assert event["metadata"]["conversation_id"] == conversation_id

                # Verify conversation state was reset
                assert conversation_id not in connector.session_manager.conversations_with_start_of_input
                assert audio_buffer.get_buffer_size() == 0

    def test_session_end_on_intent_fulfilled(self, connector):
        """Test that SESSION_END event is sent when Lex returns intent.state=Fulfilled."""
        conversation_id = "test_conv_intent_fulfilled"
        bot_id = "test_bot_123"
        session_id = "session_123"
        
        # Set up session
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        # Set up audio buffer
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        audio_buffer.add_audio_data(b"test_audio_data", encoding="ulaw")
        
        # Mock Lex response with intent.state=Fulfilled
        mock_response = {
            'interpretations': 'gAAAAABk...',  # Mock encoded interpretations
            'sessionState': 'gAAAAABk...',    # Mock encoded session state
            'messages': 'gAAAAABk...',        # Mock encoded messages
            'inputTranscript': 'gAAAAABk...'  # Mock encoded transcript
        }
        
        # No audio stream for dialog_action=Close test - this should trigger the session end path
        # mock_response['audioStream'] = None
        
        # Mock the decode method to return test data
        with patch.object(connector.response_handler, '_decode_lex_response') as mock_decode:
            mock_decode.side_effect = [
                "Book appointment",  # inputTranscript (called first)
                [{'content': 'Appointment booked successfully', 'contentType': 'PlainText'}],  # messages (called second)
                [{'intent': {'name': 'BookAppointment', 'state': 'Fulfilled'}, 'nluConfidence': {'score': 0.95}}],  # interpretations (called third)
                {'dialogAction': {'type': 'Delegate'}, 'activeContexts': []}  # sessionState (called fourth)
            ]
            
            # Mock audio conversion
            with patch('src.utils.audio_utils.convert_aws_lex_audio_to_wxcc') as mock_convert:
                mock_convert.return_value = (b"converted_audio", "audio/wav")
                
                # Mock Lex runtime call
                with patch.object(connector.lex_runtime, 'recognize_utterance', return_value=mock_response):
                    
                    # Process audio input
                    responses = list(connector._send_audio_to_lex(conversation_id))
                
                # Verify SESSION_END response was generated
                assert len(responses) == 1
                response = responses[0]
                assert response["conversation_id"] == conversation_id
                assert response["message_type"] == "session_end"
                assert response["text"] == "I've successfully completed your request. Thank you for calling!"
                assert response["response_type"] == "final"
                assert response["barge_in_enabled"] == False
                
                # Verify SESSION_END output event
                assert "output_events" in response
                assert len(response["output_events"]) == 1
                event = response["output_events"][0]
                assert event["event_type"] == "SESSION_END"
                assert event["name"] == "lex_intent_fulfilled"
                assert event["metadata"]["reason"] == "intent_fulfilled"
                assert event["metadata"]["intent_name"] == "BookAppointment"
                assert event["metadata"]["bot_name"] == "TestBot"
                assert event["metadata"]["conversation_id"] == conversation_id
                
                # Verify conversation state was reset
                assert conversation_id not in connector.session_manager.conversations_with_start_of_input
                assert audio_buffer.get_buffer_size() == 0

    def test_transfer_to_agent_on_intent_failed(self, connector):
        """Test that TRANSFER_TO_AGENT event is sent when Lex returns intent.state=Failed."""
        conversation_id = "test_conv_intent_failed"
        bot_id = "test_bot_123"
        session_id = "session_123"
        
        # Set up session
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        # Set up audio buffer
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        audio_buffer.add_audio_data(b"test_audio_data", encoding="ulaw")
        
        # Mock Lex response with intent.state=Failed
        mock_response = {
            'interpretations': 'gAAAAABk...',  # Mock encoded interpretations
            'sessionState': 'gAAAAABk...',    # Mock encoded session state
            'messages': 'gAAAAABk...',        # Mock encoded messages
            'inputTranscript': 'gAAAAABk...'  # Mock encoded transcript
        }
        
        # Mock audio stream for the response (required for normal flow)
        mock_audio_stream = MagicMock()
        mock_audio_stream.read.return_value = b"mock_audio_response"
        mock_audio_stream.close.return_value = None
        mock_response['audioStream'] = mock_audio_stream
        
        # Mock the decode method to return test data
        with patch.object(connector.response_handler, '_decode_lex_response') as mock_decode:
            mock_decode.side_effect = [
                "Complex request",  # inputTranscript (called first)
                [{'content': 'I cannot process this request', 'contentType': 'PlainText'}],  # messages (called second)
                [{'intent': {'name': 'ComplexRequest', 'state': 'Failed'}, 'nluConfidence': {'score': 0.3}}],  # interpretations (called third)
                {'dialogAction': {'type': 'ElicitIntent'}, 'activeContexts': []}  # sessionState (called fourth)
            ]
            
            # Mock audio conversion
            with patch('src.utils.audio_utils.convert_aws_lex_audio_to_wxcc') as mock_convert:
                mock_convert.return_value = (b"converted_audio", "audio/wav")
                
                # Mock Lex runtime call
                with patch.object(connector.lex_runtime, 'recognize_utterance', return_value=mock_response):
                    
                    # Process audio input
                    responses = list(connector._send_audio_to_lex(conversation_id))
                
                # Verify TRANSFER_TO_AGENT response was generated
                assert len(responses) == 1
                response = responses[0]
                assert response["conversation_id"] == conversation_id
                assert response["message_type"] == "transfer"
                assert response["text"] == "I'm having trouble with your request. Let me transfer you to a human agent."
                assert response["response_type"] == "final"
                assert response["barge_in_enabled"] == False
                
                # Verify TRANSFER_TO_AGENT output event
                assert "output_events" in response
                assert len(response["output_events"]) == 1
                event = response["output_events"][0]
                assert event["event_type"] == "TRANSFER_TO_AGENT"
                assert event["name"] == "lex_intent_failed"
                assert event["metadata"]["reason"] == "intent_failed"
                assert event["metadata"]["intent_name"] == "ComplexRequest"
                assert event["metadata"]["bot_name"] == "TestBot"
                assert event["metadata"]["conversation_id"] == conversation_id
                
                # Verify conversation state was reset
                assert conversation_id not in connector.session_manager.conversations_with_start_of_input
                assert audio_buffer.get_buffer_size() == 0

    def test_multiple_interpretations_primary_intent_handling(self, connector):
        """Test that primary interpretation (first) is used for intent state decisions."""
        conversation_id = "test_conv_multiple_intents"
        bot_id = "test_bot_123"
        session_id = "session_123"
        
        # Set up session
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        # Set up audio buffer
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        audio_buffer.add_audio_data(b"test_audio_data", encoding="ulaw")
        
        # Mock Lex response with multiple interpretations
        mock_response = {
            'interpretations': 'gAAAAABk...',  # Mock encoded interpretations
            'sessionState': 'gAAAAABk...',    # Mock encoded session state
            'messages': 'gAAAAABk...',        # Mock encoded messages
            'inputTranscript': 'gAAAAABk...'  # Mock encoded transcript
        }
        
        # Mock audio stream for the response (required for normal flow)
        mock_audio_stream = MagicMock()
        mock_audio_stream.read.return_value = b"mock_audio_response"
        mock_audio_stream.close.return_value = None
        mock_response['audioStream'] = mock_audio_stream
        
        # Mock the decode method to return test data with multiple interpretations
        with patch.object(connector.response_handler, '_decode_lex_response') as mock_decode:
            mock_decode.side_effect = [
                "Primary intent",  # inputTranscript (called first)
                [{'content': 'Primary intent fulfilled', 'contentType': 'PlainText'}],  # messages (called second)
                [
                    {'intent': {'name': 'PrimaryIntent', 'state': 'Fulfilled'}, 'nluConfidence': {'score': 0.9}},  # Primary (first)
                    {'intent': {'name': 'SecondaryIntent', 'state': 'InProgress'}, 'nluConfidence': {'score': 0.7}},  # Secondary
                    {'intent': {'name': 'TertiaryIntent', 'state': 'Failed'}, 'nluConfidence': {'score': 0.5}}   # Tertiary
                ],  # interpretations (called third)
                {'dialogAction': {'type': 'Delegate'}, 'activeContexts': []}  # sessionState (called fourth)
            ]
            
            # Mock audio conversion
            with patch('src.utils.audio_utils.convert_aws_lex_audio_to_wxcc') as mock_convert:
                mock_convert.return_value = (b"converted_audio", "audio/wav")
                
                # Mock Lex runtime call
                with patch.object(connector.lex_runtime, 'recognize_utterance', return_value=mock_response):
                    
                    # Process audio input
                    responses = list(connector._send_audio_to_lex(conversation_id))
                
                # Verify SESSION_END response was generated based on primary intent
                assert len(responses) == 1
                response = responses[0]
                assert response["message_type"] == "session_end"
                
                # Verify the primary intent was used
                event = response["output_events"][0]
                assert event["metadata"]["intent_name"] == "PrimaryIntent"
                assert event["metadata"]["reason"] == "intent_fulfilled"

    def test_no_interpretations_continues_normal_processing(self, connector):
        """Test that normal processing continues when no interpretations are present."""
        conversation_id = "test_conv_no_interpretations"
        bot_id = "test_bot_123"
        session_id = "session_id_123"
        
        # Set up session
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        # Set up audio buffer
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        audio_buffer.add_audio_data(b"test_audio_data", encoding="ulaw")
        
        # Mock Lex response with no interpretations
        mock_response = {
            'interpretations': 'gAAAAABk...',  # Mock encoded interpretations
            'sessionState': 'gAAAAABk...',    # Mock encoded session state
            'messages': 'gAAAAABk...',        # Mock encoded messages
            'inputTranscript': 'gAAAAABk...'  # Mock encoded transcript
        }
        
        # Mock the decode method to return test data
        with patch.object(connector.response_handler, '_decode_lex_response') as mock_decode:
            mock_decode.side_effect = [
                "User input",  # inputTranscript (called first)
                [{'content': 'Please provide more information', 'contentType': 'PlainText'}],  # messages (called second)
                None,  # No interpretations (called third)
                {'dialogAction': {'type': 'ElicitSlot'}, 'activeContexts': []}  # sessionState (called fourth)
            ]
            
            # Mock audio stream for normal processing
            mock_audio_stream = MagicMock()
            mock_audio_stream.read.return_value = b"mock_audio_response"
            mock_audio_stream.close.return_value = None
            mock_response['audioStream'] = mock_audio_stream
            
            # Mock audio conversion
            with patch('src.utils.audio_utils.convert_aws_lex_audio_to_wxcc') as mock_convert:
                mock_convert.return_value = (b"converted_audio", "audio/wav")
                
                # Mock Lex runtime call
                with patch.object(connector.lex_runtime, 'recognize_utterance', return_value=mock_response):
                    
                    # Process audio input
                    responses = list(connector._send_audio_to_lex(conversation_id))
                    
                    # Verify normal response was generated (not session end)
                    assert len(responses) == 1
                    response = responses[0]
                    assert response["message_type"] == "response"  # Normal response, not session_end
                    # Normal responses may have output events, so we don't check for their absence

    def test_session_end_metadata_structure(self, connector):
        """Test that SESSION_END events include proper metadata structure."""
        conversation_id = "test_conv_metadata"
        bot_id = "test_bot_123"
        session_id = "session_123"
        
        # Set up session
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        # Set up audio buffer
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        audio_buffer.add_audio_data(b"test_audio_data", encoding="ulaw")
        
        # Mock Lex response with dialog_action=Close
        mock_response = {
            'interpretations': 'gAAAAABk...',
            'sessionState': 'gAAAAABk...',
            'messages': 'gAAAAABk...',
            'inputTranscript': 'gAAAAABk...'
        }
        
        # Mock audio stream for the response (required for normal flow)
        mock_audio_stream = MagicMock()
        mock_audio_stream.read.return_value = b"mock_audio_response"
        mock_audio_stream.close.return_value = None
        mock_response['audioStream'] = mock_audio_stream
        
        # Mock the decode method
        with patch.object(connector.response_handler, '_decode_lex_response') as mock_decode:
            mock_decode.side_effect = [
                "Goodbye",  # inputTranscript (called first)
                [{'content': 'Goodbye', 'contentType': 'PlainText'}],  # messages (called second)
                [{'intent': {'name': 'Goodbye', 'state': 'InProgress'}}],  # interpretations (called third)
                {'dialogAction': {'type': 'Close'}, 'activeContexts': []}  # sessionState (called fourth)
            ]
            
            # Mock audio conversion
            with patch('src.utils.audio_utils.convert_aws_lex_audio_to_wxcc') as mock_convert:
                mock_convert.return_value = (b"converted_audio", "audio/wav")
                
                # Mock Lex runtime call
                with patch.object(connector.lex_runtime, 'recognize_utterance', return_value=mock_response):
                    
                    # Process audio input
                    responses = list(connector._send_audio_to_lex(conversation_id))
                
                # Verify metadata structure
                response = responses[0]
                event = response["output_events"][0]
                metadata = event["metadata"]
                
                # Check required metadata fields
                assert "reason" in metadata
                assert "bot_name" in metadata
                assert "conversation_id" in metadata
                
                # Check metadata values
                assert metadata["reason"] == "lex_dialog_closed"
                assert metadata["bot_name"] == "TestBot"
                assert metadata["conversation_id"] == conversation_id
                
                # Verify metadata is a dictionary (not a string or other type)
                assert isinstance(metadata, dict)
                assert len(metadata) == 3  # Should have exactly 3 fields
        conversation_id = "test_conv_794"
        bot_id = "test_bot_123"
        session_id = "session_123"
        
        # Set up session
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        # Set up initial state
        connector.session_manager.conversations_with_start_of_input.add(conversation_id)
        
        # Create DTMF message with goodbye code (6)
        message_data = {
            "input_type": "dtmf",
            "dtmf_data": {"dtmf_events": [6]}
        }
        
        # Process DTMF input
        response = connector._handle_dtmf_input(conversation_id, message_data, bot_id, session_id, "TestBot")
        
        # Verify goodbye response
        assert response["message_type"] == "goodbye"
        assert "output_events" in response
        assert response["output_events"][0]["event_type"] == "CONVERSATION_END"
        
        # Verify conversation state was reset
        assert conversation_id not in connector.session_manager.conversations_with_start_of_input

    def test_reset_integration_with_text_input(self, connector):
        """Test that conversation reset works correctly with text input."""
        conversation_id = "test_conv_795"
        
        # Set up session
        connector.session_manager._sessions[conversation_id] = {
            "session_id": "session_123",
            "actual_bot_id": "test_bot_123",
            "bot_name": "TestBot"
        }
        
        # Set up initial state
        connector.session_manager.conversations_with_start_of_input.add(conversation_id)
        
        # Process text input
        response = connector._send_text_to_lex(conversation_id, "Hello")
        
        # Verify response
        assert response["message_type"] == "silence"
        assert "Processing text input: Hello" in response["text"]
        
        # Verify conversation state was reset
        assert conversation_id not in connector.session_manager.conversations_with_start_of_input

    def test_reset_integration_with_audio_processing_errors(self, connector, mock_lex_runtime):
        """Test that conversation reset works correctly even when audio processing errors occur."""
        conversation_id = "test_conv_796"
        bot_id = "test_bot_123"
        session_id = "session_id_123"
        
        # Set up session
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        # Set up audio buffer
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        
        # Add some audio data to buffer
        audio_buffer.add_audio_data(b"test_audio", encoding="ulaw")
        assert audio_buffer.get_buffer_size() > 0
        
        # Set up initial state
        connector.session_manager.conversations_with_start_of_input.add(conversation_id)
        
        # Mock Lex runtime to raise an error
        with patch.object(connector.lex_runtime, 'recognize_utterance', side_effect=ClientError(
            {'Error': {'Code': 'ValidationException', 'Message': 'Test error'}}, 'recognize_utterance'
        )):
            # Process audio - should handle error gracefully
            responses = list(connector._send_audio_to_lex(conversation_id))
            
            # No responses should be yielded due to error
            assert len(responses) == 0
            
            # Verify conversation state was reset despite error
            assert conversation_id not in connector.session_manager.conversations_with_start_of_input
            
            # Verify audio buffer was reset
            assert audio_buffer.get_buffer_size() == 0

    def test_reset_integration_with_empty_audio_response(self, connector, mock_lex_runtime):
        """Test that conversation reset works correctly when Lex returns empty audio."""
        conversation_id = "test_conv_797"
        bot_id = "test_bot_123"
        session_id = "session_123"
        
        # Set up session
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        # Set up audio buffer
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        
        # Add some audio data to buffer
        audio_buffer.add_audio_data(b"test_audio", encoding="ulaw")
        assert audio_buffer.get_buffer_size() > 0
        
        # Set up initial state
        connector.session_manager.conversations_with_start_of_input.add(conversation_id)
        
        # Mock Lex response with empty audio stream
        mock_audio_stream = MagicMock()
        mock_audio_stream.read.return_value = b""  # Empty audio
        mock_audio_stream.close.return_value = None
        
        mock_response = {
            'audioStream': mock_audio_stream,
            'messages': 'gAAAAABk...',
            'inputTranscript': 'gAAAAABk...'
        }
        
        # Mock the decode method
        with patch.object(connector.response_handler, '_decode_lex_response') as mock_decode:
            mock_decode.side_effect = ["Test input", [{'content': 'Test response', 'contentType': 'PlainText'}]]
            
            # Mock Lex runtime call
            with patch.object(connector.lex_runtime, 'recognize_utterance', return_value=mock_response):
                # Process audio
                responses = list(connector._send_audio_to_lex(conversation_id))
                
                # No responses should be yielded due to empty audio
                assert len(responses) == 0
                
                # Verify conversation state was reset
                assert conversation_id not in connector.session_manager.conversations_with_start_of_input
                
                # Verify audio buffer was reset
                assert audio_buffer.get_buffer_size() == 0

    def test_reset_integration_with_no_audio_stream(self, connector, mock_lex_runtime):
        """Test that conversation reset works correctly when Lex response has no audio stream."""
        conversation_id = "test_conv_798"
        bot_id = "test_bot_123"
        session_id = "session_123"
        
        # Set up session
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        # Set up audio buffer
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        
        # Add some audio data to buffer
        audio_buffer.add_audio_data(b"test_audio", encoding="ulaw")
        assert audio_buffer.get_buffer_size() > 0
        
        # Set up initial state
        connector.session_manager.conversations_with_start_of_input.add(conversation_id)
        
        # Mock Lex response with no audio stream
        mock_response = {
            'messages': 'gAAAAABk...',
            'inputTranscript': 'gAAAAABk...'
            # No audioStream field
        }
        
        # Mock the decode method
        with patch.object(connector.response_handler, '_decode_lex_response') as mock_decode:
            mock_decode.side_effect = [
                "Test input",  # inputTranscript (called first)
                [{'content': 'Test response', 'contentType': 'PlainText'}],  # messages (called second)
                [{'intent': {'name': 'TestIntent', 'state': 'InProgress'}}],  # interpretations (called third)
                {'dialogAction': {'type': 'ElicitSlot'}, 'activeContexts': []}  # sessionState (called fourth)
            ]
            
            # Mock Lex runtime call
            with patch.object(connector.lex_runtime, 'recognize_utterance', return_value=mock_response):
                # Process audio
                responses = list(connector._send_audio_to_lex(conversation_id))
                
                # No responses should be yielded due to missing audio stream
                assert len(responses) == 0
                
                # Verify conversation state was reset
                assert conversation_id not in connector.session_manager.conversations_with_start_of_input
                
                # Verify audio buffer was reset
                assert audio_buffer.get_buffer_size() == 0

    def test_reset_integration_with_unexpected_errors(self, connector, mock_lex_runtime):
        """Test that conversation reset works correctly when unexpected errors occur."""
        conversation_id = "test_conv_799"
        bot_id = "test_bot_123"
        session_id = "session_123"
        
        # Set up session
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        # Set up audio buffer
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        
        # Add some audio data to buffer
        audio_buffer.add_audio_data(b"test_audio", encoding="ulaw")
        assert audio_buffer.get_buffer_size() > 0
        
        # Set up initial state
        connector.session_manager.conversations_with_start_of_input.add(conversation_id)
        
        # Mock Lex runtime to raise an unexpected error
        with patch.object(connector.lex_runtime, 'recognize_utterance', side_effect=Exception("Unexpected error")):
            # Process audio - should handle error gracefully
            responses = list(connector._send_audio_to_lex(conversation_id))
            
            # No responses should be yielded due to error
            assert len(responses) == 0
            
            # Verify conversation state was reset despite error
            assert conversation_id not in connector.session_manager.conversations_with_start_of_input
            
            # Verify audio buffer was reset
            assert audio_buffer.get_buffer_size() == 0

    def test_reset_logging_verification(self, connector):
        """Test that reset method logs appropriate messages for debugging."""
        conversation_id = "test_conv_800"
        
        # Set up initial state
        connector.session_manager.conversations_with_start_of_input.add(conversation_id)
        
        # Call the reset method
        connector.session_manager.reset_conversation_for_next_input(conversation_id)
        
        # Verify appropriate logging occurred
        connector.session_manager.logger.debug.assert_any_call(
            f"Conversation {conversation_id} reset for next audio input cycle"
        )

    def test_recognize_utterance_parameters_audio_input(self, connector):
        """Test that recognize_utterance is called with all required parameters for audio input."""
        # Set up session and audio buffer
        conversation_id = "test_conv_params_audio"
        bot_id = "test_bot_123"
        session_id = "session_123"
        
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        audio_buffer.add_audio_data(b"test_audio_data", encoding="ulaw")
        
        # Mock recognize_utterance to capture parameters
        with patch.object(connector.lex_runtime, 'recognize_utterance') as mock_recognize:
            mock_recognize.return_value = MagicMock()
            
            # Call the method
            list(connector._send_audio_to_lex(conversation_id))
            
            # Verify the method was called
            assert mock_recognize.called
            
            # Verify all required parameters are present
            call_args = mock_recognize.call_args
            assert call_args is not None
            
            # Check required parameters
            assert 'botId' in call_args.kwargs
            assert 'botAliasId' in call_args.kwargs
            assert 'localeId' in call_args.kwargs
            assert 'sessionId' in call_args.kwargs  # ← This would catch the regression!
            assert 'requestContentType' in call_args.kwargs
            assert 'responseContentType' in call_args.kwargs
            assert 'inputStream' in call_args.kwargs
            
            # Verify specific values
            assert call_args.kwargs['botId'] == bot_id
            assert call_args.kwargs['sessionId'] == session_id
            assert call_args.kwargs['botAliasId'] == connector.bot_alias_id
            assert call_args.kwargs['localeId'] == connector.locale_id
            assert call_args.kwargs['requestContentType'] == 'audio/l16; rate=16000; channels=1'
            assert call_args.kwargs['responseContentType'] == connector.response_content_type
            assert call_args.kwargs['inputStream'] is not None  # Should have audio data

    def test_recognize_utterance_parameters_text_input(self, connector):
        """Test that recognize_utterance is called with all required parameters for text input."""
        # Set up bot mapping first
        connector.session_manager._bot_name_to_id_map = {"aws_lex_connector: TestBot": "bot123"}
        
        # Set up session
        conversation_id = "test_conv_params_text"
        bot_id = "bot123"  # Use the same ID as in the mapping
        expected_session_id = f"session_{conversation_id}"  # Session manager generates this format
        
        # Let the session manager create the session properly
        # connector.session_manager._sessions[conversation_id] = {
        #     "session_id": session_id,
        #     "actual_bot_id": bot_id,
        #     "bot_name": "TestBot"
        # }
        
        # Mock recognize_utterance to capture parameters
        with patch.object(connector.lex_runtime, 'recognize_utterance') as mock_recognize:
            mock_recognize.return_value = MagicMock()
            
            # Call the method (start_conversation calls recognize_utterance)
            connector.start_conversation(conversation_id, {
                "virtual_agent_id": "aws_lex_connector: TestBot"
            })
            
            # Verify the method was called
            assert mock_recognize.called
            
            # Verify all required parameters are present
            call_args = mock_recognize.call_args
            assert call_args is not None
            
            # Check required parameters
            assert 'botId' in call_args.kwargs
            assert 'botAliasId' in call_args.kwargs
            assert 'localeId' in call_args.kwargs
            assert 'sessionId' in call_args.kwargs  # ← This would catch the regression!
            assert 'requestContentType' in call_args.kwargs
            assert 'responseContentType' in call_args.kwargs
            assert 'inputStream' in call_args.kwargs
            
            # Verify specific values
            assert call_args.kwargs['botId'] == bot_id
            assert call_args.kwargs['sessionId'] == expected_session_id
            assert call_args.kwargs['botAliasId'] == connector.bot_alias_id
            assert call_args.kwargs['localeId'] == connector.locale_id
            assert call_args.kwargs['requestContentType'] == connector.request_content_type
            assert call_args.kwargs['responseContentType'] == connector.response_content_type
            assert call_args.kwargs['inputStream'] is not None  # Should have text data

    def test_recognize_utterance_parameters_validation_error(self, connector):
        """Test that missing sessionId parameter would cause validation error."""
        # Set up session and audio buffer
        conversation_id = "test_conv_params_validation"
        bot_id = "test_bot_123"
        session_id = "session_123"
        
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        audio_buffer.add_audio_data(b"test_audio_data", encoding="ulaw")
        
        # Mock recognize_utterance to simulate the missing sessionId error
        with patch.object(connector.lex_runtime, 'recognize_utterance') as mock_recognize:
            # Simulate the exact error that occurred
            mock_recognize.side_effect = ClientError(
                {'Error': {'Code': 'ParamValidationError', 'Message': 'Missing required parameter in input: "sessionId"'}},
                'RecognizeUtterance'
            )
            
            # Call the method - it should handle the error gracefully
            responses = list(connector._send_audio_to_lex(conversation_id))
            
            # Verify the method was called (even though it failed)
            assert mock_recognize.called
            
            # Verify error handling worked (no responses should be yielded due to error)
            assert len(responses) == 0

    def test_recognize_utterance_parameters_barge_in_enabled(self, mock_config_barge_in_enabled):
        """Test that recognize_utterance parameters are correct when barge-in is enabled."""
        with patch('boto3.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session.client.side_effect = lambda service: {
                'lexv2-models': MagicMock(),
                'lexv2-runtime': MagicMock()
            }[service]
            mock_session_class.return_value = mock_session
            
            connector = AWSLexConnector(mock_config_barge_in_enabled)
            connector.logger = MagicMock()
            connector.session_manager.logger = MagicMock()
            
            # Set up session
            conversation_id = "test_conv_barge_in"
            bot_id = "test_bot_123"
            session_id = "session_123"
            
            connector.session_manager._sessions[conversation_id] = {
                "session_id": session_id,
                "actual_bot_id": bot_id,
                "bot_name": "TestBot"
            }
            
            connector.audio_processor.init_audio_buffer(conversation_id)
            audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
            audio_buffer.add_audio_data(b"test_audio_data", encoding="ulaw")
            
            # Mock recognize_utterance to capture parameters
            with patch.object(connector.lex_runtime, 'recognize_utterance') as mock_recognize:
                mock_recognize.return_value = MagicMock()
                
                # Call the method
                list(connector._send_audio_to_lex(conversation_id))
                
                # Verify the method was called
                assert mock_recognize.called
                
                # Verify all required parameters are present
                call_args = mock_recognize.call_args
                assert call_args is not None
                
                # Check required parameters
                assert 'botId' in call_args.kwargs
                assert 'botAliasId' in call_args.kwargs
                assert 'localeId' in call_args.kwargs
                assert 'sessionId' in call_args.kwargs  # ← Critical for barge-in to work!
                assert 'requestContentType' in call_args.kwargs
                assert 'responseContentType' in call_args.kwargs
                assert 'inputStream' in call_args.kwargs
                
                # Verify barge-in configuration is properly applied
                assert connector.barge_in_enabled is True

    def test_recognize_utterance_parameters_barge_in_disabled(self, connector):
        """Test that recognize_utterance parameters are correct when barge-in is disabled."""
        # Set up session and audio buffer
        conversation_id = "test_conv_barge_in_disabled"
        bot_id = "test_bot_123"
        session_id = "session_123"
        
        connector.session_manager._sessions[conversation_id] = {
            "session_id": session_id,
            "actual_bot_id": bot_id,
            "bot_name": "TestBot"
        }
        
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        audio_buffer.add_audio_data(b"test_audio_data", encoding="ulaw")
        
        # Mock recognize_utterance to capture parameters
        with patch.object(connector.lex_runtime, 'recognize_utterance') as mock_recognize:
            mock_recognize.return_value = MagicMock()
            
            # Call the method
            list(connector._send_audio_to_lex(conversation_id))
            
            # Verify the method was called
            assert mock_recognize.called
            
            # Verify all required parameters are present
            call_args = mock_recognize.call_args
            assert call_args is not None
            
            # Check required parameters
            assert 'botId' in call_args.kwargs
            assert 'botAliasId' in call_args.kwargs
            assert 'localeId' in call_args.kwargs
            assert 'sessionId' in call_args.kwargs  # ← Critical for barge-in to work!
            assert 'requestContentType' in call_args.kwargs
            assert 'responseContentType' in call_args.kwargs
            assert 'inputStream' in call_args.kwargs
            
            # Verify barge-in configuration is properly applied
            assert connector.barge_in_enabled is False

    def test_recognize_utterance_parameters_consistency(self, connector):
        """Test that both text and audio recognize_utterance calls use consistent parameters."""
        # Set up bot mapping first
        connector.session_manager._bot_name_to_id_map = {"aws_lex_connector: TestBot": "bot123"}
        
        # Set up session
        conversation_id = "test_conv_consistency"
        bot_id = "bot123"  # Use the same ID as in the mapping
        expected_session_id = f"session_{conversation_id}"  # Session manager generates this format
        
        # Test text input parameters
        with patch.object(connector.lex_runtime, 'recognize_utterance') as mock_recognize_text:
            mock_recognize_text.return_value = MagicMock()
            
            connector.start_conversation(conversation_id, {
                "virtual_agent_id": "aws_lex_connector: TestBot"
            })
            
            text_call_args = mock_recognize_text.call_args
            assert text_call_args is not None
            
        # Test audio input parameters
        connector.audio_processor.init_audio_buffer(conversation_id)
        audio_buffer = connector.audio_processor.audio_buffers[conversation_id]
        audio_buffer.add_audio_data(b"test_audio_data", encoding="ulaw")
        
        with patch.object(connector.lex_runtime, 'recognize_utterance') as mock_recognize_audio:
            mock_recognize_audio.return_value = MagicMock()
            
            list(connector._send_audio_to_lex(conversation_id))
            
            audio_call_args = mock_recognize_audio.call_args
            assert audio_call_args is not None
            
        # Verify both calls have the same required parameters
        required_params = ['botId', 'botAliasId', 'localeId', 'sessionId', 'requestContentType', 'responseContentType', 'inputStream']
        
        for param in required_params:
            assert param in text_call_args.kwargs, f"Text call missing {param}"
            assert param in audio_call_args.kwargs, f"Audio call missing {param}"
            
        # Verify sessionId is the same in both calls
        assert text_call_args.kwargs['sessionId'] == audio_call_args.kwargs['sessionId']
        assert text_call_args.kwargs['sessionId'] == expected_session_id


if __name__ == "__main__":
    pytest.main([__file__])
