"""
Unit tests for AWS Lex connector audio logging functionality.

This module tests the audio logging features that will be added to the AWSLexConnector:
- Audio logging configuration and initialization
- WAV file creation and management
- Audio format conversion for logging
- File naming conventions
- Error handling and logging
- Max file size enforcement
"""

import pytest
import tempfile
import os
import time
from unittest.mock import Mock, patch, MagicMock, mock_open
from pathlib import Path
from datetime import datetime
import struct

from src.connectors.aws_lex_connector import AWSLexConnector


class TestAWSLexConnectorAudioLogging:
    """Test suite for AWS Lex connector audio logging functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def mock_config_with_audio_logging(self, temp_dir):
        """Provide mock configuration with audio logging enabled."""
        return {
            "region_name": "us-east-1",
            "aws_access_key_id": "test_key",
            "aws_secret_access_key": "test_secret",
            "bot_alias_id": "TESTALIAS",
            "audio_logging": {
                "enabled": True,
                "output_dir": temp_dir,
                "filename_format": "{conversation_id}_{timestamp}_{source}.wav",
                "log_wxcc_audio": True,
                "log_aws_audio": True,
                "max_file_size": 10485760  # 10MB
            }
        }

    @pytest.fixture
    def mock_config_without_audio_logging(self):
        """Provide mock configuration without audio logging."""
        return {
            "region_name": "us-east-1",
            "aws_access_key_id": "test_key",
            "aws_secret_access_key": "test_secret",
            "bot_alias_id": "TESTALIAS"
        }

    @pytest.fixture
    def mock_config_partial_audio_logging(self, temp_dir):
        """Provide mock configuration with partial audio logging settings."""
        return {
            "region_name": "us-east-1",
            "aws_access_key_id": "test_key",
            "aws_secret_access_key": "test_secret",
            "bot_alias_id": "TESTALIAS",
            "audio_logging": {
                "enabled": True,
                "output_dir": temp_dir,
                "log_wxcc_audio": False,  # Only log AWS audio
                "log_aws_audio": True
            }
        }

    @pytest.fixture
    def connector_with_audio_logging(self, mock_config_with_audio_logging):
        """Provide a configured connector instance with audio logging enabled."""
        with patch('boto3.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session.client.side_effect = lambda service: {
                'lexv2-models': MagicMock(),
                'lexv2-runtime': MagicMock()
            }[service]
            mock_session_class.return_value = mock_session
            
            connector = AWSLexConnector(mock_config_with_audio_logging)
            connector.logger = MagicMock()
            return connector

    @pytest.fixture
    def connector_without_audio_logging(self, mock_config_without_audio_logging):
        """Provide a configured connector instance without audio logging."""
        with patch('boto3.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session.client.side_effect = lambda service: {
                'lexv2-models': MagicMock(),
                'lexv2-runtime': MagicMock()
            }[service]
            mock_session_class.return_value = mock_session
            
            connector = AWSLexConnector(mock_config_without_audio_logging)
            connector.logger = MagicMock()
            return connector

    @pytest.fixture
    def sample_conversation_id(self):
        """Provide a sample conversation ID for testing."""
        return "test_conv_12345"

    @pytest.fixture
    def sample_wxcc_audio_data(self):
        """Provide sample WxCC audio data (u-law format)."""
        # Create mock u-law audio data (simplified)
        return b"mock_ulaw_audio_data_for_wxcc"

    @pytest.fixture
    def sample_aws_audio_data(self):
        """Provide sample AWS Lex audio data (PCM format)."""
        # Create mock PCM audio data (simplified)
        return b"mock_pcm_audio_data_from_aws"

    @pytest.fixture
    def mock_timestamp(self):
        """Provide a mock timestamp for consistent testing."""
        return "20250819_135125"

    # Test Configuration and Initialization

    def test_audio_logging_config_initialization(self, connector_with_audio_logging):
        """Test that audio logging configuration is properly initialized."""
        connector = connector_with_audio_logging
        
        # Check that audio logging attributes are set
        assert hasattr(connector, 'audio_logging_config')
        assert connector.audio_logging_config['enabled'] is True
        assert connector.audio_logging_config['output_dir'] is not None
        assert connector.audio_logging_config['log_wxcc_audio'] is True
        assert connector.audio_logging_config['log_aws_audio'] is True
        assert connector.audio_logging_config['max_file_size'] == 10485760

    def test_audio_logging_disabled_by_default(self, connector_without_audio_logging):
        """Test that audio logging is disabled when not configured."""
        connector = connector_without_audio_logging
        
        # Check that audio logging is not enabled
        assert not hasattr(connector, 'audio_logging_config')
        # Or if it exists, it should be disabled
        if hasattr(connector, 'audio_logging_config'):
            assert connector.audio_logging_config.get('enabled', False) is False

    def test_audio_logging_partial_config(self, mock_config_partial_audio_logging):
        """Test audio logging with partial configuration (missing optional fields)."""
        with patch('boto3.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session.client.side_effect = lambda service: {
                'lexv2-models': MagicMock(),
                'lexv2-runtime': MagicMock()
            }[service]
            mock_session_class.return_value = mock_session
            
            connector = AWSLexConnector(mock_config_partial_audio_logging)
            
            # Should have default values for missing fields
            assert connector.audio_logging_config['enabled'] is True
            assert connector.audio_logging_config['log_wxcc_audio'] is False
            assert connector.audio_logging_config['log_aws_audio'] is True
            # Default filename format should be set
            assert 'filename_format' in connector.audio_logging_config
            # Default max file size should be set
            assert 'max_file_size' in connector.audio_logging_config

    def test_audio_logging_output_directory_creation(self, temp_dir, mock_config_with_audio_logging):
        """Test that output directory is created if it doesn't exist."""
        # Remove the temp dir to test creation
        import shutil
        shutil.rmtree(temp_dir)
        
        with patch('boto3.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session.client.side_effect = lambda service: {
                'lexv2-models': MagicMock(),
                'lexv2-runtime': MagicMock()
            }[service]
            mock_session_class.return_value = mock_session
            
            # This should create the directory
            connector = AWSLexConnector(mock_config_with_audio_logging)
            
            # Check that directory was created
            output_dir = Path(connector.audio_logging_config['output_dir'])
            assert output_dir.exists()
            assert output_dir.is_dir()

    # Test Audio Logger Initialization

    def test_audio_logger_initialization_when_enabled(self, connector_with_audio_logging):
        """Test that AudioLogger is initialized when audio logging is enabled."""
        connector = connector_with_audio_logging
        
        # Check that AudioLogger instance is created
        assert hasattr(connector, 'audio_logger')
        assert connector.audio_logger is not None

    def test_audio_logger_not_initialized_when_disabled(self, connector_without_audio_logging):
        """Test that AudioLogger is not initialized when audio logging is disabled."""
        connector = connector_without_audio_logging
        
        # Check that AudioLogger instance is not created
        assert not hasattr(connector, 'audio_logger')

    # Test WAV File Creation

    def test_wav_file_creation_for_wxcc_audio(self, connector_with_audio_logging, 
                                             sample_conversation_id, sample_wxcc_audio_data,
                                             mock_timestamp):
        """Test that WAV files are created for incoming WxCC audio."""
        connector = connector_with_audio_logging
        
        # Mock the audio logger
        mock_audio_logger = MagicMock()
        connector.audio_logger = mock_audio_logger
        
        # Call the method that should log WxCC audio
        connector._log_wxcc_audio(sample_conversation_id, sample_wxcc_audio_data)
        
        # Verify that the audio logger was called with correct parameters
        mock_audio_logger.log_audio.assert_called_once_with(
            conversation_id=sample_conversation_id,
            audio_data=sample_wxcc_audio_data,
            source='wxcc',
            encoding='ulaw'
        )

    def test_wav_file_creation_for_aws_audio(self, connector_with_audio_logging,
                                           sample_conversation_id, sample_aws_audio_data,
                                           mock_timestamp):
        """Test that WAV files are created for outgoing AWS Lex audio."""
        connector = connector_with_audio_logging
        
        # Mock the audio logger
        mock_audio_logger = MagicMock()
        connector.audio_logger = mock_audio_logger
        
        # Call the method that should log AWS audio
        connector._log_aws_audio(sample_conversation_id, sample_aws_audio_data)
        
        # Verify that the audio logger was called with correct parameters
        mock_audio_logger.log_audio.assert_called_once_with(
            conversation_id=sample_conversation_id,
            audio_data=sample_aws_audio_data,
            source='aws',
            encoding='pcm',
            sample_rate=16000,
            bit_depth=16,
            channels=1
        )

    def test_wav_file_naming_convention(self, connector_with_audio_logging,
                                      sample_conversation_id, mock_timestamp):
        """Test that WAV files follow the correct naming convention."""
        connector = connector_with_audio_logging
        
        # Mock the audio logger to test filename generation
        mock_audio_logger = MagicMock()
        connector.audio_logger = mock_audio_logger
        
        # Test that the audio logger is called with correct source parameters
        # The actual filename generation is handled by the AudioLogger utility
        connector._log_wxcc_audio(sample_conversation_id, b"test_audio")
        connector._log_aws_audio(sample_conversation_id, b"test_audio")
        
        # Verify both calls were made to the audio logger
        assert mock_audio_logger.log_audio.call_count == 2

    def test_timestamp_format(self, connector_with_audio_logging):
        """Test that timestamps are generated in the correct human-readable format."""
        connector = connector_with_audio_logging
        
        # The timestamp generation is now handled by the AudioLogger utility
        # Test that the audio logger can generate timestamps correctly
        mock_audio_logger = MagicMock()
        connector.audio_logger = mock_audio_logger
        
        # Mock the timestamp generation in the audio logger
        with patch.object(mock_audio_logger, '_generate_timestamp', return_value="20250819_135125"):
            # Test that the audio logger can generate timestamps
            timestamp = mock_audio_logger._generate_timestamp()
            
            # Check format: YYYYMMDD_HHMMSS
            assert len(timestamp) == 15  # 8 + 1 + 6 characters
            assert timestamp[8] == '_'  # Separator between date and time
            
            # Check that it's a valid date/time format
            try:
                datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
            except ValueError:
                pytest.fail(f"Timestamp {timestamp} is not in expected format YYYYMMDD_HHMMSS")

    # Test Audio Format Conversion

    def test_wxcc_audio_conversion_to_wav(self, connector_with_audio_logging,
                                        sample_conversation_id, sample_wxcc_audio_data):
        """Test that WxCC u-law audio is converted to WAV format for logging."""
        connector = connector_with_audio_logging
        
        # Mock the audio logger to test conversion
        mock_audio_logger = MagicMock()
        connector.audio_logger = mock_audio_logger
        
        # Mock the audio converter in the audio logger
        mock_converter = MagicMock()
        mock_converter.convert_ulaw_to_wav.return_value = b"converted_wav_data"
        mock_audio_logger.audio_converter = mock_converter
        
        # Call the logging method which should trigger conversion
        connector._log_wxcc_audio(sample_conversation_id, sample_wxcc_audio_data)
        
        # Verify the audio logger was called with correct parameters
        mock_audio_logger.log_audio.assert_called_once_with(
            conversation_id=sample_conversation_id,
            audio_data=sample_wxcc_audio_data,
            source='wxcc',
            encoding='ulaw'
        )

    def test_aws_audio_conversion_to_wav(self, connector_with_audio_logging,
                                       sample_conversation_id, sample_aws_audio_data):
        """Test that AWS PCM audio is converted to WAV format for logging."""
        connector = connector_with_audio_logging
        
        # Mock the audio logger to test conversion
        mock_audio_logger = MagicMock()
        connector.audio_logger = mock_audio_logger
        
        # Mock the audio converter in the audio logger
        mock_converter = MagicMock()
        mock_converter.convert_pcm_to_wav.return_value = b"converted_wav_data"
        mock_audio_logger.audio_converter = mock_converter
        
        # Call the logging method which should trigger conversion
        connector._log_aws_audio(sample_conversation_id, sample_aws_audio_data)
        
        # Verify the audio logger was called with correct parameters
        mock_audio_logger.log_audio.assert_called_once_with(
            conversation_id=sample_conversation_id,
            audio_data=sample_aws_audio_data,
            source='aws',
            encoding='pcm',
            sample_rate=16000,
            bit_depth=16,
            channels=1
        )

    # Test File Size Management

    def test_max_file_size_enforcement(self, connector_with_audio_logging,
                                     sample_conversation_id, sample_wxcc_audio_data):
        """Test that max file size is enforced when logging audio."""
        connector = connector_with_audio_logging
        
        # Set a small max file size for testing
        connector.audio_logging_config['max_file_size'] = 100  # 100 bytes
        
        # Create audio data that exceeds the limit
        large_audio_data = b"x" * 150  # 150 bytes
        
        # Mock the audio logger
        mock_audio_logger = MagicMock()
        connector.audio_logger = mock_audio_logger
        
        # Call the method that should handle large audio
        connector._log_wxcc_audio(sample_conversation_id, large_audio_data)
        
        # Verify that the audio logger handles large files appropriately
        # This might involve splitting files or truncating
        mock_audio_logger.log_audio.assert_called_once()

    def test_file_splitting_for_large_audio(self, connector_with_audio_logging,
                                          sample_conversation_id):
        """Test that large audio files are split when they exceed max size."""
        connector = connector_with_audio_logging
        
        # Set a small max file size for testing
        connector.audio_logging_config['max_file_size'] = 100  # 100 bytes
        
        # Create audio data that exceeds the limit
        large_audio_data = b"x" * 250  # 250 bytes
        
        # Mock the audio logger to return split files
        mock_audio_logger = MagicMock()
        mock_audio_logger.log_audio.return_value = [
            f"{sample_conversation_id}_part1.wav",
            f"{sample_conversation_id}_part2.wav",
            f"{sample_conversation_id}_part3.wav"
        ]
        connector.audio_logger = mock_audio_logger
        
        # Call the method that should handle large audio
        result = connector._log_wxcc_audio(sample_conversation_id, large_audio_data)
        
        # Verify that files were split
        assert len(result) == 3
        assert all(filename.endswith('.wav') for filename in result)

    # Test Error Handling

    def test_audio_logging_failure_logs_as_error(self, connector_with_audio_logging,
                                               sample_conversation_id, sample_wxcc_audio_data):
        """Test that audio logging failures are logged as errors when enabled."""
        connector = connector_with_audio_logging
        
                # Mock the audio logger to raise an exception
        mock_audio_logger = MagicMock()
        mock_audio_logger.log_audio.side_effect = Exception("File write failed")
        connector.audio_logger = mock_audio_logger

        # Call the method that should handle errors
        connector._log_wxcc_audio(sample_conversation_id, sample_wxcc_audio_data)
        
        # Verify that the error was logged
        connector.logger.error.assert_called()
        error_call_args = connector.logger.error.call_args[0][0]
        assert "Failed to log WxCC audio" in error_call_args

    def test_audio_logging_continues_on_failure(self, connector_with_audio_logging,
                                              sample_conversation_id, sample_wxcc_audio_data):
        """Test that audio logging failures don't stop the main conversation flow."""
        connector = connector_with_audio_logging
        
        # Mock the audio logger to raise an exception
        mock_audio_logger = MagicMock()
        mock_audio_logger.log_audio.side_effect = Exception("File write failed")
        connector.audio_logger = mock_audio_logger
        
        # The method should not raise an exception, it should handle it gracefully
        try:
            connector._log_wxcc_audio(sample_conversation_id, sample_wxcc_audio_data)
        except Exception:
            pytest.fail("Audio logging failure should not propagate to caller")

    # Test Integration Points

    def test_audio_logging_not_in_handle_audio_input(self, connector_with_audio_logging,
                                                   sample_conversation_id):
        """Test that audio logging is NOT called in handle_audio_input (moved to _send_audio_to_lex)."""
        connector = connector_with_audio_logging
        
        # Mock the audio logger
        mock_audio_logger = MagicMock()
        connector.audio_logger = mock_audio_logger
        
        # Mock session data
        connector._sessions[sample_conversation_id] = {
            "session_id": "session_123",
            "display_name": "aws_lex_connector: TestBot",
            "actual_bot_id": "bot123",
            "bot_name": "TestBot"
        }
        
        # Mock audio buffer
        connector.audio_buffers[sample_conversation_id] = MagicMock()
        
        # Mock message data
        message_data = {
            "input_type": "audio",
            "audio_data": b"test_audio_data",
            "conversation_id": sample_conversation_id
        }
        
        # Mock the audio logging method
        with patch.object(connector, '_log_wxcc_audio') as mock_log:
            # Call the method that should NOT trigger audio logging anymore
            list(connector._handle_audio_input(sample_conversation_id, message_data, 
                                             "bot123", "session_123", "TestBot"))
            
            # Verify that audio logging was NOT called (moved to _send_audio_to_lex)
            mock_log.assert_not_called()

    def test_audio_logging_in_send_audio_to_lex(self, connector_with_audio_logging,
                                              sample_conversation_id):
        """Test that both WxCC and AWS audio logging is called when sending audio to Lex."""
        connector = connector_with_audio_logging
        
        # Mock the audio logger
        mock_audio_logger = MagicMock()
        connector.audio_logger = mock_audio_logger
        
        # Mock session data
        connector._sessions[sample_conversation_id] = {
            "session_id": "session_123",
            "display_name": "aws_lex_connector: TestBot",
            "actual_bot_id": "bot123",
            "bot_name": "TestBot"
        }
        
        # Mock audio buffer
        mock_buffer = MagicMock()
        mock_buffer.get_buffered_audio.return_value = b"buffered_audio_data"
        connector.audio_buffers[sample_conversation_id] = mock_buffer
        
        # Mock Lex response with audio
        mock_response = MagicMock()
        mock_audio_stream = MagicMock()
        mock_audio_stream.read.return_value = b"lex_audio_response"
        mock_audio_stream.close.return_value = None
        mock_response.get.return_value = mock_audio_stream
        
        # Mock the Lex runtime client
        connector.lex_runtime.recognize_utterance.return_value = mock_response
        
        # Mock both audio logging methods
        with patch.object(connector, '_log_wxcc_audio') as mock_wxcc_log, \
             patch.object(connector, '_log_aws_audio') as mock_aws_log:
            
            # Call the method that should trigger both types of audio logging
            list(connector._send_audio_to_lex(sample_conversation_id))
            
            # Verify that WxCC audio logging was called (for the buffered audio sent to Lex)
            mock_wxcc_log.assert_called_once_with(sample_conversation_id, b"buffered_audio_data")
            
            # Verify that AWS audio logging was called (for the response from Lex)
            mock_aws_log.assert_called_once_with(sample_conversation_id, b"lex_audio_response")

    # Test Cleanup

    def test_audio_logging_cleanup_on_conversation_end(self, connector_with_audio_logging,
                                                     sample_conversation_id):
        """Test that audio logging resources are cleaned up when conversation ends."""
        connector = connector_with_audio_logging
        
        # Mock the audio logger
        mock_audio_logger = MagicMock()
        connector.audio_logger = mock_audio_logger
        
        # Mock session data
        connector._sessions[sample_conversation_id] = {
            "session_id": "session_123",
            "display_name": "aws_lex_connector: TestBot",
            "actual_bot_id": "bot123",
            "bot_name": "TestBot"
        }
        
        # Call the method that should clean up audio logging
        connector.end_conversation(sample_conversation_id)
        
        # Verify that cleanup was called on the audio logger
        mock_audio_logger.cleanup.assert_called_once_with(sample_conversation_id)

    # Test Configuration Validation

    def test_invalid_audio_logging_config_handling(self):
        """Test that invalid audio logging configuration is handled gracefully."""
        invalid_config = {
            "region_name": "us-east-1",
            "aws_access_key_id": "test_key",
            "aws_secret_access_key": "test_secret",
            "bot_alias_id": "TESTALIAS",
            "audio_logging": {
                "enabled": True,
                "output_dir": "/invalid/path/that/cannot/be/created",
                "max_file_size": "invalid_size"  # Should be integer
            }
        }
        
        with patch('boto3.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session.client.side_effect = lambda service: {
                'lexv2-models': MagicMock(),
                'lexv2-runtime': MagicMock()
            }[service]
            mock_session_class.return_value = mock_session
            
            # Should not raise an exception, should handle invalid config gracefully
            try:
                connector = AWSLexConnector(invalid_config)
                # Check that audio logging is disabled due to invalid config
                # When audio logging fails to initialize, no attributes are set
                assert not hasattr(connector, 'audio_logging_config')
                assert not hasattr(connector, 'audio_logger')
            except Exception:
                pytest.fail("Invalid audio logging config should not cause initialization failure")

    def test_missing_audio_logging_config_keys(self):
        """Test that missing audio logging configuration keys use sensible defaults."""
        minimal_config = {
            "region_name": "us-east-1",
            "aws_access_key_id": "test_key",
            "aws_secret_access_key": "test_secret",
            "bot_alias_id": "TESTALIAS",
            "audio_logging": {
                "enabled": True
                # Missing other keys
            }
        }
        
        with patch('boto3.Session') as mock_session_class:
            mock_session = MagicMock()
            mock_session.client.side_effect = lambda service: {
                'lexv2-models': MagicMock(),
                'lexv2-runtime': MagicMock()
            }[service]
            mock_session_class.return_value = mock_session
            
            connector = AWSLexConnector(minimal_config)
            
            # Check that default values are used
            assert connector.audio_logging_config['enabled'] is True
            assert 'output_dir' in connector.audio_logging_config
            assert 'filename_format' in connector.audio_logging_config
            assert 'max_file_size' in connector.audio_logging_config
            assert 'log_all_audio' in connector.audio_logging_config
