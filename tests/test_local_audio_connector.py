"""
Unit tests for the Local Audio Connector.

This module tests the LocalAudioConnector class functionality including:
- Initialization and configuration
- Audio file management and conversion
- Message handling (audio, DTMF, events)
- Audio recording capabilities
- Conversation lifecycle management
- Error handling and fallbacks
"""

import pytest
from unittest.mock import MagicMock, patch, Mock, call
import logging
from pathlib import Path
import tempfile
import shutil
from typing import Dict, Any

from src.connectors.local_audio_connector import LocalAudioConnector


class TestLocalAudioConnector:
    """Test suite for LocalAudioConnector."""

    @pytest.fixture
    def mock_config(self):
        """Provide a mock configuration for testing."""
        return {
            "agent_id": "TestAgent",
            "audio_base_path": "test_audio",
            "record_caller_audio": True,
            "audio_recording": {
                "output_dir": "test_recordings",
                "silence_threshold": 3000,
                "silence_duration": 2.0,
                "quiet_threshold": 20
            },
            "audio_files": {
                "welcome": "welcome.wav",
                "transfer": "transfer.wav",
                "goodbye": "goodbye.wav",
                "error": "error.wav",
                "default": "default.wav"
            }
        }

    @pytest.fixture
    def mock_config_minimal(self):
        """Provide a minimal configuration for testing."""
        return {
            "agent_id": "MinimalAgent"
        }

    @pytest.fixture
    def mock_audio_converter(self):
        """Provide a mock audio converter."""
        mock_converter = MagicMock()
        mock_converter.convert_any_audio_to_wxcc.return_value = b"converted_audio"
        mock_converter.detect_audio_encoding.return_value = "pcm_16bit"
        return mock_converter

    @pytest.fixture
    def mock_audio_recorder(self):
        """Provide a mock audio recorder."""
        mock_recorder = MagicMock()
        mock_recorder.add_audio_data.return_value = None
        mock_recorder.finalize_recording.return_value = "test_recording.wav"
        mock_recorder.check_silence_timeout.return_value = False
        return mock_recorder

    @pytest.fixture
    def temp_audio_dir(self):
        """Provide a temporary directory for audio files."""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def connector(self, mock_config, temp_audio_dir):
        """Provide a configured connector instance for testing."""
        # Update config to use temp directory
        mock_config["audio_base_path"] = str(temp_audio_dir)
        
        with patch('src.connectors.local_audio_connector.AudioConverter') as mock_converter_class:
            mock_converter = MagicMock()
            mock_converter.convert_any_audio_to_wxcc.return_value = b"converted_audio"
            mock_converter.detect_audio_encoding.return_value = "pcm_16bit"
            mock_converter_class.return_value = mock_converter
            
            connector = LocalAudioConnector(mock_config)
            connector.logger = MagicMock()
            return connector

    def test_init_with_full_config(self, mock_config, temp_audio_dir):
        """Test connector initialization with full configuration."""
        mock_config["audio_base_path"] = str(temp_audio_dir)
        
        with patch('src.connectors.local_audio_connector.AudioConverter'):
            connector = LocalAudioConnector(mock_config)
            
            assert connector.agent_id == "TestAgent"
            assert connector.audio_base_path == Path(temp_audio_dir)
            assert connector.record_caller_audio is True
            assert connector.audio_recording_config == mock_config["audio_recording"]
            assert connector.audio_files == mock_config["audio_files"]
            assert connector.audio_recorders == {}

    def test_init_with_minimal_config(self, mock_config_minimal):
        """Test connector initialization with minimal configuration."""
        with patch('src.connectors.local_audio_connector.AudioConverter'):
            connector = LocalAudioConnector(mock_config_minimal)
            
            assert connector.agent_id == "MinimalAgent"
            assert connector.audio_base_path == Path("audio")
            assert connector.record_caller_audio is False
            assert connector.audio_recording_config == {}
            assert connector.audio_files == {
                "welcome": "welcome.wav",
                "transfer": "transferring.wav",
                "goodbye": "goodbye.wav",
                "error": "error.wav",
                "default": "default_response.wav"
            }

    def test_init_creates_audio_directory(self, mock_config, temp_audio_dir):
        """Test that audio directory is created if it doesn't exist."""
        new_audio_dir = temp_audio_dir / "new_audio"
        mock_config["audio_base_path"] = str(new_audio_dir)
        
        with patch('src.connectors.local_audio_connector.AudioConverter'):
            connector = LocalAudioConnector(mock_config)
            
            assert new_audio_dir.exists()
            assert connector.audio_base_path == new_audio_dir

    def test_get_available_agents(self, connector):
        """Test getting available agent IDs."""
        agents = connector.get_available_agents()
        
        expected_agents = ["Local Audio: TestAgent"]
        assert agents == expected_agents

    def test_start_conversation_success(self, connector, temp_audio_dir):
        """Test successful conversation start."""
        # Create a test audio file
        welcome_file = temp_audio_dir / "welcome.wav"
        welcome_file.write_bytes(b"fake_wav_data")
        
        response = connector.start_conversation("conv123", {})
        
        assert response["conversation_id"] == "conv123"
        assert response["agent_id"] == "TestAgent"
        assert response["message_type"] == "welcome"
        assert "welcome to the webex contact center" in response["text"]
        assert response["audio_content"] == b"converted_audio"
        assert response["barge_in_enabled"] is False

    def test_start_conversation_with_recording_enabled(self, connector):
        """Test conversation start with audio recording enabled."""
        with patch.object(connector, '_init_audio_recorder') as mock_init_recorder:
            response = connector.start_conversation("conv123", {})
            
            mock_init_recorder.assert_called_once_with("conv123")
            assert response["message_type"] == "welcome"

    def test_start_conversation_audio_conversion_failure(self, connector, temp_audio_dir):
        """Test conversation start when audio conversion fails."""
        # Create a test audio file
        welcome_file = temp_audio_dir / "welcome.wav"
        welcome_file.write_bytes(b"fake_wav_data")
        
        # Mock audio conversion to fail
        connector._convert_audio_to_wxcc_format = MagicMock(side_effect=Exception("Conversion failed"))
        
        response = connector.start_conversation("conv123", {})
        
        assert response["audio_content"] == b""
        assert response["message_type"] == "welcome"
        connector.logger.error.assert_called()

    def test_send_message_conversation_start(self, connector):
        """Test handling of conversation start message."""
        message_data = {
            "input_type": "conversation_start",
            "conversation_id": "conv123"
        }
        
        response = list(connector.send_message("conv123", message_data))
        assert len(response) == 1
        assert response[0]["message_type"] == "silence"

    def test_send_message_dtmf_transfer(self, connector, temp_audio_dir):
        """Test handling of DTMF transfer request (digit 5)."""
        # Create a test transfer audio file
        transfer_file = temp_audio_dir / "transfer.wav"
        transfer_file.write_bytes(b"fake_transfer_data")
        
        message_data = {
            "input_type": "dtmf",
            "dtmf_data": {"dtmf_events": [5]},
            "conversation_id": "conv123"
        }
        
        response = list(connector.send_message("conv123", message_data))
        assert len(response) == 1
        assert response[0]["message_type"] == "transfer"

    def test_send_message_dtmf_goodbye(self, connector, temp_audio_dir):
        """Test handling of DTMF goodbye request (digit 6)."""
        # Create a test goodbye audio file
        goodbye_file = temp_audio_dir / "goodbye.wav"
        goodbye_file.write_bytes(b"fake_goodbye_data")
        
        message_data = {
            "input_type": "dtmf",
            "dtmf_data": {"dtmf_events": [6]},  # Single digit 6 for goodbye
            "conversation_id": "conv123"
        }
        
        response = list(connector.send_message("conv123", message_data))
        assert len(response) == 1
        assert response[0]["message_type"] == "goodbye"

    def test_send_message_dtmf_other_digits(self, connector):
        """Test handling of other DTMF digits."""
        message_data = {
            "input_type": "dtmf",
            "dtmf_data": {"dtmf_events": [1, 2, 3]},
            "conversation_id": "conv123"
        }
        
        response = list(connector.send_message("conv123", message_data))
        assert len(response) == 1
        assert response[0]["message_type"] == "silence"
        assert response[0]["conversation_id"] == "conv123"
        connector.logger.info.assert_any_call("DTMF digits entered: 123")

    def test_send_message_dtmf_no_events(self, connector):
        """Test handling of DTMF input with no events."""
        message_data = {
            "input_type": "dtmf",
            "dtmf_data": {},
            "conversation_id": "conv123"
        }
        
        response = list(connector.send_message("conv123", message_data))
        assert len(response) == 1
        assert response[0]["message_type"] == "silence"

    def test_send_message_event(self, connector):
        """Test handling of event input."""
        message_data = {
            "input_type": "event",
            "event_data": {"name": "test_event"},
            "conversation_id": "conv123"
        }
        
        response = list(connector.send_message("conv123", message_data))
        assert len(response) == 1
        assert response[0]["message_type"] == "silence"

    def test_send_message_audio_input(self, connector):
        """Test handling of audio input."""
        message_data = {
            "input_type": "audio",
            "audio_data": b"test_audio_bytes",
            "conversation_id": "conv123"
        }
        
        with patch.object(connector, '_process_audio_for_recording') as mock_process:
            response = list(connector.send_message("conv123", message_data))
            assert len(response) == 1
            mock_process.assert_called_once_with(b"test_audio_bytes", "conv123")

    def test_send_message_audio_input_with_recording_disabled(self, connector):
        """Test handling of audio input when recording is disabled."""
        connector.record_caller_audio = False
        
        message_data = {
            "input_type": "audio",
            "audio_data": b"test_audio_bytes",
            "conversation_id": "conv123"
        }
        
        with patch.object(connector, '_process_audio_for_recording') as mock_process:
            response = list(connector.send_message("conv123", message_data))
            
            mock_process.assert_not_called()
            assert response[0]["message_type"] == "silence"

    def test_send_message_unrecognized_input(self, connector):
        """Test handling of unrecognized input type."""
        message_data = {
            "input_type": "unknown_type",
            "conversation_id": "conv123"
        }
        
        response = list(connector.send_message("conv123", message_data))
        assert len(response) == 1
        assert response[0]["message_type"] == "silence"

    def test_end_conversation_success(self, connector):
        """Test successful conversation ending."""
        # Set up a mock audio recorder
        connector.audio_recorders["conv123"] = MagicMock()
        connector.audio_recorders["conv123"].finalize_recording.return_value = "test_recording.wav"
        
        connector.end_conversation("conv123")
        
        assert "conv123" not in connector.audio_recorders
        connector.logger.info.assert_called()

    def test_end_conversation_with_message_data(self, connector):
        """Test ending conversation with message data."""
        connector.end_conversation("conv123", {"test": "data"})
        
        connector.logger.debug.assert_called_with("End conversation message data: {'test': 'data'}")

    def test_end_conversation_no_recording(self, connector):
        """Test ending conversation without audio recording."""
        connector.record_caller_audio = False
        
        connector.end_conversation("conv123")
        
        # Should not try to finalize recording
        assert "conv123" not in connector.audio_recorders

    def test_convert_wxcc_to_vendor_audio(self, connector):
        """Test conversion from WxCC to vendor format for audio input."""
        # Mock gRPC data object
        mock_grpc_data = MagicMock()
        mock_grpc_data.voice_va_input_type = "AUDIO"
        mock_grpc_data.audio_input.caller_audio = b"audio_data"
        mock_grpc_data.audio_input.encoding = "ULAW"
        mock_grpc_data.audio_input.sample_rate_hertz = 8000
        mock_grpc_data.audio_input.language_code = "en-US"
        
        result = connector.convert_wxcc_to_vendor(mock_grpc_data)
        
        assert result["input_type"] == "audio"
        assert result["audio_data"] == b"audio_data"
        assert result["encoding"] == "ULAW"
        assert result["sample_rate"] == 8000
        assert result["language_code"] == "en-US"

    def test_convert_wxcc_to_vendor_dtmf(self, connector):
        """Test conversion from WxCC to vendor format for DTMF input."""
        # Create a mock that doesn't have audio_input attribute
        mock_grpc_data = MagicMock()
        # Set the required attribute
        type(mock_grpc_data).voice_va_input_type = "DTMF"
        # Explicitly remove audio_input attribute
        del mock_grpc_data.audio_input
        mock_grpc_data.dtmf_input.dtmf_digits = "123"
        
        result = connector.convert_wxcc_to_vendor(mock_grpc_data)
        
        assert result["type"] == "dtmf"
        assert result["dtmf_digits"] == "123"

    def test_convert_wxcc_to_vendor_event(self, connector):
        """Test conversion from WxCC to vendor format for event input."""
        # Create a mock that doesn't have audio_input or dtmf_input attributes
        mock_grpc_data = MagicMock()
        # Set the required attribute
        type(mock_grpc_data).voice_va_input_type = "EVENT"
        # Explicitly remove attributes that would cause it to go to other paths
        del mock_grpc_data.audio_input
        del mock_grpc_data.dtmf_input
        mock_grpc_data.event_input.event_type = "test_event"
        
        result = connector.convert_wxcc_to_vendor(mock_grpc_data)
        
        assert result["type"] == "event"
        assert result["event_type"] == "test_event"

    def test_convert_wxcc_to_vendor_unknown(self, connector):
        """Test conversion from WxCC to vendor format for unknown input."""
        # Create a mock that doesn't have voice_va_input_type attribute
        mock_grpc_data = MagicMock()
        # Explicitly remove voice_va_input_type attribute so it falls through to the fallback
        del mock_grpc_data.voice_va_input_type
        
        result = connector.convert_wxcc_to_vendor(mock_grpc_data)
        
        assert result == mock_grpc_data

    def test_convert_vendor_to_wxcc_success(self, connector):
        """Test conversion from vendor to WxCC format."""
        vendor_data = {
            "text": "Hello world",
            "conversation_id": "conv123",
            "agent_id": "TestAgent",
            "message_type": "welcome"
        }
        
        result = connector.convert_vendor_to_wxcc(vendor_data)
        
        assert result["text"] == "Hello world"
        assert result["conversation_id"] == "conv123"
        assert result["agent_id"] == "TestAgent"
        assert result["message_type"] == "welcome"
        assert result["input_sensitive"] is False
        assert result["input_mode"] == "VOICE"
        assert len(result["prompts"]) == 1
        assert result["prompts"][0]["text"] == "Hello world"

    def test_convert_vendor_to_wxcc_goodbye(self, connector):
        """Test conversion from vendor to WxCC format for goodbye message."""
        vendor_data = {
            "text": "Goodbye",
            "conversation_id": "conv123",
            "message_type": "goodbye"
        }
        
        result = connector.convert_vendor_to_wxcc(vendor_data)
        
        assert result["output_events"][0]["event_type"] == "CONVERSATION_END"
        assert result["output_events"][0]["name"] == "conversation_ended"
        assert result["output_events"][0]["metadata"]["reason"] == "user_requested_end"

    def test_convert_vendor_to_wxcc_transfer(self, connector):
        """Test conversion from vendor to WxCC format for transfer message."""
        vendor_data = {
            "text": "Transferring",
            "conversation_id": "conv123",
            "message_type": "transfer"
        }
        
        result = connector.convert_vendor_to_wxcc(vendor_data)
        
        assert result["output_events"][0]["event_type"] == "TRANSFER_TO_HUMAN"
        assert result["output_events"][0]["name"] == "transfer_requested"
        assert result["output_events"][0]["metadata"]["reason"] == "user_requested_transfer"

    def test_convert_vendor_to_wxcc_not_dict(self, connector):
        """Test conversion from vendor to WxCC format when input is not a dict."""
        result = connector.convert_vendor_to_wxcc("not_a_dict")
        
        assert result == "not_a_dict"

    def test_init_audio_recorder_success(self, connector):
        """Test successful audio recorder initialization."""
        with patch('src.connectors.local_audio_connector.AudioRecorder') as mock_recorder_class:
            mock_recorder = MagicMock()
            mock_recorder_class.return_value = mock_recorder
            
            connector._init_audio_recorder("conv123")
            
            assert "conv123" in connector.audio_recorders
            assert connector.audio_recorders["conv123"] == mock_recorder
            mock_recorder_class.assert_called_once()

    def test_init_audio_recorder_already_exists(self, connector):
        """Test audio recorder initialization when one already exists."""
        connector.audio_recorders["conv123"] = MagicMock()
        
        connector._init_audio_recorder("conv123")
        
        # Should not create a new one
        connector.logger.info.assert_called_with(
            "Audio recorder already exists for conversation conv123"
        )

    def test_init_audio_recorder_failure(self, connector):
        """Test audio recorder initialization failure."""
        with patch('src.connectors.local_audio_connector.AudioRecorder') as mock_recorder_class:
            mock_recorder_class.side_effect = Exception("Recorder creation failed")
            
            connector._init_audio_recorder("conv123")
            
            # Should not add to recorders dict
            assert "conv123" not in connector.audio_recorders
            connector.logger.error.assert_called()

    def test_process_audio_for_recording_success(self, connector):
        """Test successful audio processing for recording."""
        connector.record_caller_audio = True
        
        with patch.object(connector, '_init_audio_recorder') as mock_init:
            with patch.object(connector, 'extract_audio_data') as mock_extract:
                mock_extract.return_value = b"extracted_audio"
                
                connector._process_audio_for_recording(b"input_audio", "conv123")
                
                mock_init.assert_called_once_with("conv123")
                # The recorder should be initialized but may not be added if initialization fails
                # We're testing the method call, not the final state

    def test_process_audio_for_recording_recording_disabled(self, connector):
        """Test audio processing when recording is disabled."""
        connector.record_caller_audio = False
        
        with patch.object(connector, '_init_audio_recorder') as mock_init:
            connector._process_audio_for_recording(b"input_audio", "conv123")
            
            mock_init.assert_not_called()

    def test_process_audio_for_recording_no_audio_data(self, connector):
        """Test audio processing with no audio data."""
        connector.record_caller_audio = True
        
        with patch.object(connector, '_init_audio_recorder') as mock_init:
            connector._process_audio_for_recording(None, "conv123")
            
            mock_init.assert_not_called()

    def test_process_audio_for_recording_extraction_failure(self, connector):
        """Test audio processing when audio extraction fails."""
        connector.record_caller_audio = True
        
        with patch.object(connector, '_init_audio_recorder') as mock_init:
            with patch.object(connector, 'extract_audio_data') as mock_extract:
                mock_extract.return_value = None
                
                connector._process_audio_for_recording(b"input_audio", "conv123")
                
                mock_init.assert_called_once()
                # The method returns early when extraction fails, so no error is logged
                # We're testing the early return behavior

    def test_process_audio_for_recording_processing_failure(self, connector):
        """Test audio processing when processing fails."""
        connector.record_caller_audio = True
        
        with patch.object(connector, '_init_audio_recorder') as mock_init:
            # Mock the recorder initialization to actually add a recorder
            def mock_init_side_effect(conv_id):
                connector.audio_recorders[conv_id] = MagicMock()
            mock_init.side_effect = mock_init_side_effect
            
            with patch.object(connector, 'extract_audio_data') as mock_extract:
                mock_extract.return_value = b"extracted_audio"
                
                # Mock process_audio_format to fail
                with patch.object(connector, 'process_audio_format') as mock_process:
                    mock_process.side_effect = Exception("Processing failed")
                    
                    connector._process_audio_for_recording(b"input_audio", "conv123")
                    
                    mock_init.assert_called_once()
                    # Verify that process_audio_format was called
                    mock_process.assert_called_once()
                    # The method catches exceptions and logs them, so error should be called
                    connector.logger.error.assert_called()

    def test_convert_audio_to_wxcc_format_success(self, connector):
        """Test successful audio conversion to WxCC format."""
        audio_path = Path("test_audio.wav")
        
        result = connector._convert_audio_to_wxcc_format(audio_path)
        
        assert result == b"converted_audio"
        connector.audio_converter.convert_any_audio_to_wxcc.assert_called_once_with(audio_path)

    def test_convert_audio_to_wxcc_format_failure(self, connector):
        """Test audio conversion failure."""
        audio_path = Path("test_audio.wav")
        
        # Mock converter to fail
        connector.audio_converter.convert_any_audio_to_wxcc.side_effect = Exception("Conversion failed")
        
        result = connector._convert_audio_to_wxcc_format(audio_path)
        
        assert result == b""
        connector.logger.error.assert_called()

    def test_check_silence_timeout_recording_enabled(self, connector):
        """Test silence timeout check when recording is enabled."""
        connector.record_caller_audio = True
        connector.audio_recorders["conv123"] = MagicMock()
        
        connector.check_silence_timeout("conv123", True, connector.audio_recorders, connector.logger)
        
        connector.audio_recorders["conv123"].check_silence_timeout.assert_called_once()

    def test_check_silence_timeout_recording_disabled(self, connector):
        """Test silence timeout check when recording is disabled."""
        connector.record_caller_audio = False
        
        connector.check_silence_timeout("conv123", False, {}, connector.logger)
        
        # Should not do anything when recording is disabled

    def test_check_silence_timeout_no_recorder(self, connector):
        """Test silence timeout check when no recorder exists."""
        connector.record_caller_audio = True
        
        connector.check_silence_timeout("conv123", True, {}, connector.logger)
        
        # Should not do anything when no recorder exists

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


if __name__ == "__main__":
    pytest.main([__file__])
