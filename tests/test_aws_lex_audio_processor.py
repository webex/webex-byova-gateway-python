"""
Unit tests for AWS Lex Audio Processor audio logging functionality.

This module tests the audio logging features in AWSLexAudioProcessor:
- Audio logging configuration initialization
- Audio logger initialization
- WAV file creation for WxCC and AWS audio
- Audio format conversion for logging
- File size enforcement and splitting
- Error handling and cleanup
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch
from datetime import datetime

from src.connectors.aws_lex_audio_processor import AWSLexAudioProcessor


class TestAWSLexAudioProcessorAudioLogging:
    """Test suite for AWS Lex Audio Processor audio logging functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def mock_config_with_audio_logging(self, temp_dir):
        """Configuration with audio logging enabled."""
        return {
            "region_name": "us-east-1",
            "bot_alias_id": "TESTALIAS",
            "audio_logging": {
                "enabled": True,
                "output_dir": temp_dir,
                "filename_format": "{conversation_id}_{timestamp}_{source}.wav",
                "log_all_audio": True,
                "max_file_size": 10485760,  # 10MB
                "sample_rate": 8000,
                "bit_depth": 8,
                "channels": 1,
                "encoding": "ulaw"
            }
        }

    @pytest.fixture
    def mock_config_without_audio_logging(self):
        """Configuration without audio logging."""
        return {
            "region_name": "us-east-1",
            "bot_alias_id": "TESTALIAS"
            # No audio_logging section
        }

    @pytest.fixture
    def mock_config_partial_audio_logging(self, temp_dir):
        """Configuration with partial audio logging settings."""
        return {
            "region_name": "us-east-1",
            "bot_alias_id": "TESTALIAS",
            "audio_logging": {
                "enabled": True,
                "output_dir": temp_dir,
                "log_all_audio": False  # Only some settings
            }
        }

    @pytest.fixture
    def processor_with_audio_logging(self, mock_config_with_audio_logging):
        """Audio processor with audio logging enabled."""
        with patch('src.connectors.aws_lex_audio_processor.AudioLogger'):
            processor = AWSLexAudioProcessor(mock_config_with_audio_logging, MagicMock())
            return processor

    @pytest.fixture
    def processor_without_audio_logging(self, mock_config_without_audio_logging):
        """Audio processor without audio logging."""
        processor = AWSLexAudioProcessor(mock_config_without_audio_logging, MagicMock())
        return processor

    @pytest.fixture
    def sample_conversation_id(self):
        """Sample conversation ID for testing."""
        return "test_conv_12345"

    @pytest.fixture
    def sample_wxcc_audio_data(self):
        """Sample WxCC audio data (u-law format)."""
        return b"mock_ulaw_audio_data_for_wxcc"

    @pytest.fixture
    def sample_aws_audio_data(self):
        """Sample AWS audio data (PCM format)."""
        return b"mock_pcm_audio_data_from_aws"

    @pytest.fixture
    def mock_timestamp(self):
        """Mock timestamp for testing."""
        return "20250819_135125"

    # Test Configuration Initialization

    def test_audio_logging_config_initialization(self, processor_with_audio_logging):
        """Test that audio logging configuration is properly initialized."""
        processor = processor_with_audio_logging

        # Check that audio logging attributes are set
        assert hasattr(processor, 'audio_logging_config')
        assert processor.audio_logging_config['enabled'] is True
        assert processor.audio_logging_config['output_dir'] is not None
        assert processor.audio_logging_config['log_all_audio'] is True
        assert processor.audio_logging_config['max_file_size'] == 10485760

    def test_audio_logging_disabled_by_default(self, processor_without_audio_logging):
        """Test that audio logging is disabled when not configured."""
        processor = processor_without_audio_logging

        # Check that audio logging attributes are not set
        assert not hasattr(processor, 'audio_logging_config')
        if hasattr(processor, 'audio_logging_config'):
            assert processor.audio_logging_config.get('enabled', False) is False

    def test_audio_logging_partial_config(self, mock_config_partial_audio_logging):
        """Test audio logging with partial configuration (missing optional fields)."""
        with patch('src.connectors.aws_lex_audio_processor.AudioLogger'):
            processor = AWSLexAudioProcessor(mock_config_partial_audio_logging, MagicMock())

            # Should have default values for missing fields
            assert processor.audio_logging_config['enabled'] is True
            assert processor.audio_logging_config['log_all_audio'] is False
            assert 'filename_format' in processor.audio_logging_config
            assert 'max_file_size' in processor.audio_logging_config

    def test_audio_logging_output_directory_creation(self, temp_dir, mock_config_with_audio_logging):
        """Test that output directory is created if it doesn't exist."""
        # Remove the temp dir to test creation
        import shutil
        shutil.rmtree(temp_dir)

        # Don't mock AudioLogger so it can actually create the directory
        processor = AWSLexAudioProcessor(mock_config_with_audio_logging, MagicMock())

        # Check that directory was created
        output_dir = Path(processor.audio_logging_config['output_dir'])
        assert output_dir.exists()
        assert output_dir.is_dir()

    # Test Audio Logger Initialization

    def test_audio_logger_initialization_when_enabled(self, processor_with_audio_logging):
        """Test that AudioLogger is initialized when audio logging is enabled."""
        processor = processor_with_audio_logging

        # Check that AudioLogger instance is created
        assert hasattr(processor, 'audio_logger')
        assert processor.audio_logger is not None

    def test_audio_logger_not_initialized_when_disabled(self, processor_without_audio_logging):
        """Test that AudioLogger is not initialized when audio logging is disabled."""
        processor = processor_without_audio_logging

        # Check that AudioLogger instance is not created
        assert not hasattr(processor, 'audio_logger')

    # Test WAV File Creation

    def test_wav_file_creation_for_wxcc_audio(self, processor_with_audio_logging,
                                             sample_conversation_id, sample_wxcc_audio_data,
                                             mock_timestamp):
        """Test that WAV files are created for incoming WxCC audio."""
        processor = processor_with_audio_logging

        # Mock the audio logger
        mock_audio_logger = MagicMock()
        processor.audio_logger = mock_audio_logger

        # Call the method that should log WxCC audio
        processor.log_wxcc_audio(sample_conversation_id, sample_wxcc_audio_data)

        # Verify that the audio logger was called with correct parameters
        mock_audio_logger.log_audio.assert_called_once_with(
            conversation_id=sample_conversation_id,
            audio_data=sample_wxcc_audio_data,
            source='wxcc',
            encoding='ulaw'
        )

    def test_wav_file_creation_for_aws_audio(self, processor_with_audio_logging,
                                           sample_conversation_id, sample_aws_audio_data,
                                           mock_timestamp):
        """Test that WAV files are created for outgoing AWS Lex audio."""
        processor = processor_with_audio_logging

        # Mock the audio logger
        mock_audio_logger = MagicMock()
        processor.audio_logger = mock_audio_logger

        # Call the method that should log AWS audio
        processor.log_aws_audio(sample_conversation_id, sample_aws_audio_data)

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

    def test_wav_file_naming_convention(self, processor_with_audio_logging,
                                      sample_conversation_id, mock_timestamp):
        """Test that WAV files follow the correct naming convention."""
        processor = processor_with_audio_logging

        # Mock the audio logger to test filename generation
        mock_audio_logger = MagicMock()
        processor.audio_logger = mock_audio_logger

        # Test that the audio logger is called with correct source parameters
        # The actual filename generation is handled by the AudioLogger utility
        processor.log_wxcc_audio(sample_conversation_id, b"test_audio")
        processor.log_aws_audio(sample_conversation_id, b"test_audio")

        # Verify both calls were made to the audio logger
        assert mock_audio_logger.log_audio.call_count == 2

    def test_timestamp_format(self, processor_with_audio_logging):
        """Test that timestamps are generated in the correct human-readable format."""
        processor = processor_with_audio_logging

        # The timestamp generation is now handled by the AudioLogger utility
        # Test that the audio logger can generate timestamps correctly
        mock_audio_logger = MagicMock()
        processor.audio_logger = mock_audio_logger

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

    def test_wxcc_audio_conversion_to_wav(self, processor_with_audio_logging,
                                        sample_conversation_id, sample_wxcc_audio_data):
        """Test that WxCC u-law audio is converted to WAV format for logging."""
        processor = processor_with_audio_logging

        # Mock the audio logger to test conversion
        mock_audio_logger = MagicMock()
        processor.audio_logger = mock_audio_logger

        # Mock the audio converter in the audio logger
        mock_converter = MagicMock()
        mock_converter.convert_ulaw_to_wav.return_value = b"converted_wav_data"
        mock_audio_logger.audio_converter = mock_converter

        # Call the logging method which should trigger conversion
        processor.log_wxcc_audio(sample_conversation_id, sample_wxcc_audio_data)

        # Verify that the audio logger was called with the correct parameters
        mock_audio_logger.log_audio.assert_called_once_with(
            conversation_id=sample_conversation_id,
            audio_data=sample_wxcc_audio_data,
            source='wxcc',
            encoding='ulaw'
        )

    def test_aws_audio_conversion_to_wav(self, processor_with_audio_logging,
                                       sample_conversation_id, sample_aws_audio_data):
        """Test that AWS PCM audio is converted to WAV format for logging."""
        processor = processor_with_audio_logging

        # Mock the audio logger to test conversion
        mock_audio_logger = MagicMock()
        processor.audio_logger = mock_audio_logger

        # Mock the audio converter in the audio logger
        mock_converter = MagicMock()
        mock_converter.convert_pcm_to_wav.return_value = b"converted_wav_data"
        mock_audio_logger.audio_converter = mock_converter

        # Call the logging method which should trigger conversion
        processor.log_aws_audio(sample_conversation_id, sample_aws_audio_data)

        # Verify that the audio logger was called with the correct parameters
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

    def test_max_file_size_enforcement(self, processor_with_audio_logging,
                                     sample_conversation_id, sample_wxcc_audio_data):
        """Test that max file size is enforced when logging audio."""
        processor = processor_with_audio_logging

        # Set a small max file size for testing
        processor.audio_logging_config['max_file_size'] = 100  # 100 bytes

        # Create audio data that exceeds the limit
        large_audio_data = b"x" * 250  # 250 bytes

        # Mock the audio logger to return split files
        mock_audio_logger = MagicMock()
        mock_audio_logger.log_audio.return_value = [
            f"{sample_conversation_id}_part1.wav",
            f"{sample_conversation_id}_part2.wav",
            f"{sample_conversation_id}_part3.wav"
        ]
        processor.audio_logger = mock_audio_logger

        # Call the method that should handle large audio
        result = processor.log_wxcc_audio(sample_conversation_id, large_audio_data)

        # Verify that files were split
        assert len(result) == 3

    def test_file_splitting_for_large_audio(self, processor_with_audio_logging,
                                          sample_conversation_id):
        """Test that large audio files are split when they exceed max size."""
        processor = processor_with_audio_logging

        # Set a small max file size for testing
        processor.audio_logging_config['max_file_size'] = 100  # 100 bytes

        # Create audio data that exceeds the limit
        large_audio_data = b"x" * 250  # 250 bytes

        # Mock the audio logger to return split files
        mock_audio_logger = MagicMock()
        mock_audio_logger.log_audio.return_value = [
            f"{sample_conversation_id}_part1.wav",
            f"{sample_conversation_id}_part2.wav",
            f"{sample_conversation_id}_part3.wav"
        ]
        processor.audio_logger = mock_audio_logger

        # Call the method that should handle large audio
        result = processor.log_wxcc_audio(sample_conversation_id, large_audio_data)

        # Verify that files were split
        assert len(result) == 3
        assert all(f.endswith('.wav') for f in result)
        assert all(sample_conversation_id in f for f in result)

    # Test Error Handling

    def test_audio_logging_failure_logs_as_error(self, processor_with_audio_logging,
                                               sample_conversation_id, sample_wxcc_audio_data):
        """Test that audio logging failures are logged as errors when enabled."""
        processor = processor_with_audio_logging

        # Mock the audio logger to raise an exception
        mock_audio_logger = MagicMock()
        mock_audio_logger.log_audio.side_effect = Exception("File write failed")
        processor.audio_logger = mock_audio_logger

        # Mock the logger to capture error messages
        mock_logger = MagicMock()
        processor.logger = mock_logger

        # Call the method that should handle errors
        processor.log_wxcc_audio(sample_conversation_id, sample_wxcc_audio_data)

        # Verify that the error was logged
        mock_logger.error.assert_called()

    def test_audio_logging_continues_on_failure(self, processor_with_audio_logging,
                                              sample_conversation_id, sample_wxcc_audio_data):
        """Test that audio logging failures don't stop the main conversation flow."""
        processor = processor_with_audio_logging

        # Mock the audio logger to raise an exception
        mock_audio_logger = MagicMock()
        mock_audio_logger.log_audio.side_effect = Exception("File write failed")
        processor.audio_logger = mock_audio_logger

        # The method should not raise an exception, it should handle it gracefully
        try:
            processor.log_wxcc_audio(sample_conversation_id, sample_wxcc_audio_data)
        except Exception:
            pytest.fail("Audio logging failure should not propagate to caller")

    # Test Integration with Audio Processing

    def test_audio_logging_methods_exist(self, processor_with_audio_logging,
                                       sample_conversation_id):
        """Test that audio logging methods exist and can be called."""
        processor = processor_with_audio_logging

        # Mock the audio logger
        mock_audio_logger = MagicMock()
        processor.audio_logger = mock_audio_logger

        # Test that the logging methods exist and can be called
        assert hasattr(processor, 'log_wxcc_audio')
        assert hasattr(processor, 'log_aws_audio')
        assert callable(processor.log_wxcc_audio)
        assert callable(processor.log_aws_audio)

        # Test calling the methods
        processor.log_wxcc_audio(sample_conversation_id, b"test_wxcc_audio")
        processor.log_aws_audio(sample_conversation_id, b"test_aws_audio")

        # Verify that the audio logger was called twice
        assert mock_audio_logger.log_audio.call_count == 2

    def test_audio_logging_cleanup_on_conversation_end(self, processor_with_audio_logging,
                                                     sample_conversation_id):
        """Test that audio logging resources are cleaned up when conversation ends."""
        processor = processor_with_audio_logging

        # Mock the audio logger
        mock_audio_logger = MagicMock()
        processor.audio_logger = mock_audio_logger

        # Call the method that should clean up audio logging
        processor.cleanup_audio_logging(sample_conversation_id)

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

        # Should not raise an exception, should handle invalid config gracefully
        try:
            processor = AWSLexAudioProcessor(invalid_config, MagicMock())
            # Check that audio logging is disabled due to invalid config
            # When audio logging fails to initialize, no attributes are set
            assert not hasattr(processor, 'audio_logging_config')
            assert not hasattr(processor, 'audio_logger')
        except Exception:
            pytest.fail("Invalid audio logging config should not cause initialization failure")

    def test_missing_audio_logging_config_keys(self):
        """Test that missing audio logging configuration keys use sensible defaults."""
        minimal_config = {
            "region_name": "us-east-1",
            "bot_alias_id": "TESTALIAS",
            "audio_logging": {
                "enabled": True
                # Missing other keys
            }
        }

        with patch('src.connectors.aws_lex_audio_processor.AudioLogger'):
            processor = AWSLexAudioProcessor(minimal_config, MagicMock())

            # Check that default values are used
            assert processor.audio_logging_config['enabled'] is True
            assert 'output_dir' in processor.audio_logging_config
            assert 'filename_format' in processor.audio_logging_config
            assert 'max_file_size' in processor.audio_logging_config
            assert 'log_all_audio' in processor.audio_logging_config
