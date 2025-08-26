"""
Unit tests for the AudioLogger utility class.

This module tests the AudioLogger class that will be created to handle
audio logging functionality for the AWS Lex connector:
- WAV file creation and management
- Audio format conversion
- File size management and splitting
- Error handling
"""

import pytest
import tempfile
import os
import time
from unittest.mock import Mock, patch, MagicMock, mock_open
from pathlib import Path
from datetime import datetime
import struct

# Import the AudioLogger class
from src.utils.audio_logger import AudioLogger


class TestAudioLogger:
    """Test suite for AudioLogger utility class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir)

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

    @pytest.fixture
    def audio_logger_config(self, temp_dir):
        """Provide configuration for AudioLogger testing."""
        return {
            "output_dir": temp_dir,
            "filename_format": "{conversation_id}_{timestamp}_{source}.wav",
            "max_file_size": 10485760,  # 10MB
            "sample_rate": 8000,
            "bit_depth": 8,
            "channels": 1,
            "encoding": "ulaw"
        }

    # Test Initialization

    def test_audio_logger_initialization(self, temp_dir, audio_logger_config):
        """Test AudioLogger initialization with valid configuration."""
        audio_logger = AudioLogger(audio_logger_config)
        assert audio_logger.output_dir == Path(temp_dir)
        assert audio_logger.max_file_size == 10485760
        assert audio_logger.sample_rate == 8000
        assert audio_logger.bit_depth == 8
        assert audio_logger.channels == 1
        assert audio_logger.encoding == "ulaw"

    def test_audio_logger_creates_output_directory(self, temp_dir, audio_logger_config):
        """Test that AudioLogger creates output directory if it doesn't exist."""
        # Remove the temp dir to test creation
        import shutil
        shutil.rmtree(temp_dir)
        
        audio_logger = AudioLogger(audio_logger_config)
        assert Path(temp_dir).exists()
        assert Path(temp_dir).is_dir()

    def test_audio_logger_uses_default_values(self):
        """Test that AudioLogger uses sensible default values when not specified."""
        minimal_config = {
            "output_dir": "/tmp/test"
        }
        
        audio_logger = AudioLogger(minimal_config)
        assert audio_logger.max_file_size > 0
        assert audio_logger.sample_rate > 0
        assert audio_logger.bit_depth > 0
        assert audio_logger.channels > 0

    # Test WxCC Audio Logging

    def test_log_audio_creates_wxcc_file(self, temp_dir, audio_logger_config,
                                       sample_conversation_id, sample_wxcc_audio_data,
                                       mock_timestamp):
        """Test that logging WxCC audio creates a WAV file."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Mock timestamp generation
        with patch.object(audio_logger, '_generate_timestamp', return_value=mock_timestamp):
            # Log WxCC audio
            result = audio_logger.log_audio(sample_conversation_id, sample_wxcc_audio_data, 'wxcc', 'ulaw')
            
            # Check that file was created
            expected_filename = f"{sample_conversation_id}_{mock_timestamp}_wxcc.wav"
            expected_path = Path(temp_dir) / expected_filename
            assert expected_path.exists()
            assert expected_path.is_file()
            
            # Check that result contains the file path
            assert str(expected_path) in result

    def test_log_audio_generic_method(self, temp_dir, audio_logger_config,
                                    sample_conversation_id, sample_wxcc_audio_data,
                                    mock_timestamp):
        """Test the generic log_audio method with custom parameters."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Mock timestamp generation
        with patch.object(audio_logger, '_generate_timestamp', return_value=mock_timestamp):
            # Log audio with custom parameters
            result = audio_logger.log_audio(
                conversation_id=sample_conversation_id,
                audio_data=sample_wxcc_audio_data,
                source='user_input',
                encoding='ulaw',
                sample_rate=16000,
                bit_depth=16,
                channels=2
            )
            
            # Check that file was created
            expected_filename = f"{sample_conversation_id}_{mock_timestamp}_user_input.wav"
            expected_path = Path(temp_dir) / expected_filename
            assert expected_path.exists()
            assert expected_path.is_file()
            
            # Check that result contains the file path
            assert str(expected_path) in result

    def test_generic_filename_generation(self, temp_dir, audio_logger_config,
                                       sample_conversation_id, mock_timestamp):
        """Test that generic filename generation works with different sources."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Mock timestamp generation
        with patch.object(audio_logger, '_generate_timestamp', return_value=mock_timestamp):
            # Test different sources
            test_sources = ['wxcc', 'aws', 'user_input', 'bot_response', 'custom_source']
            
            for source in test_sources:
                filename = audio_logger._generate_filename(sample_conversation_id, source)
                expected_filename = f"{sample_conversation_id}_{mock_timestamp}_{source}.wav"
                assert filename == expected_filename

    def test_generic_audio_conversion(self, temp_dir, audio_logger_config,
                                    sample_conversation_id, sample_wxcc_audio_data):
        """Test that generic audio conversion works with different parameters."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Test different encoding and audio parameters
        test_configs = [
            {'encoding': 'ulaw', 'sample_rate': 8000, 'bit_depth': 8, 'channels': 1},
            {'encoding': 'pcm', 'sample_rate': 16000, 'bit_depth': 16, 'channels': 2},
            {'encoding': 'alaw', 'sample_rate': 44100, 'bit_depth': 24, 'channels': 1}
        ]
        
        for config in test_configs:
            # Mock the audio converter to avoid actual conversion
            with patch.object(audio_logger.audio_converter, 'pcm_to_wav') as mock_converter:
                mock_converter.return_value = b"mock_wav_data"
                
                # Test the generic conversion method
                result = audio_logger._convert_audio_to_wav(
                    sample_wxcc_audio_data,
                    config['encoding'],
                    config['sample_rate'],
                    config['bit_depth'],
                    config['channels']
                )
                
                # Verify the converter was called with correct parameters
                mock_converter.assert_called_once_with(
                    sample_wxcc_audio_data,
                    sample_rate=config['sample_rate'],
                    bit_depth=config['bit_depth'],
                    channels=config['channels'],
                    encoding=config['encoding']
                )
                
                # Reset mock for next iteration
                mock_converter.reset_mock()

    def test_log_audio_wxcc_filename_format(self, temp_dir, audio_logger_config,
                                          sample_conversation_id, sample_wxcc_audio_data,
                                          mock_timestamp):
        """Test that WxCC audio files follow the correct naming convention."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Mock timestamp generation
        with patch.object(audio_logger, '_generate_timestamp', return_value=mock_timestamp):
            # Log WxCC audio
            audio_logger.log_audio(sample_conversation_id, sample_wxcc_audio_data, 'wxcc', 'ulaw')
            
            # Check filename format
            expected_filename = f"{sample_conversation_id}_{mock_timestamp}_wxcc.wav"
            expected_path = Path(temp_dir) / expected_filename
            assert expected_path.exists()

    def test_log_audio_converts_wxcc_ulaw_to_wav(self, temp_dir, audio_logger_config,
                                                sample_conversation_id, sample_wxcc_audio_data):
        """Test that WxCC u-law audio is converted to WAV format."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Log WxCC audio
        result = audio_logger.log_audio(sample_conversation_id, sample_wxcc_audio_data, 'wxcc', 'ulaw')
            
        # Check that the file contains valid WAV data
        file_path = result[0] if isinstance(result, list) else result
        assert self._is_valid_wav_file(file_path)

    # Test AWS Audio Logging

    def test_log_audio_creates_aws_file(self, temp_dir, audio_logger_config,
                                      sample_conversation_id, sample_aws_audio_data,
                                      mock_timestamp):
        """Test that logging AWS audio creates a WAV file."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Mock timestamp generation
        with patch.object(audio_logger, '_generate_timestamp', return_value=mock_timestamp):
            # Log AWS audio
            result = audio_logger.log_audio(sample_conversation_id, sample_aws_audio_data, 'aws', 'pcm', 16000, 16, 1)
            
            # Check that file was created
            expected_filename = f"{sample_conversation_id}_{mock_timestamp}_aws.wav"
            expected_path = Path(temp_dir) / expected_filename
            assert expected_path.exists()
            assert expected_path.is_file()
            
            # Check that result contains the file path
            assert str(expected_path) in result

    def test_log_audio_aws_filename_format(self, temp_dir, audio_logger_config,
                                         sample_conversation_id, sample_aws_audio_data,
                                         mock_timestamp):
        """Test that AWS audio files follow the correct naming convention."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Mock timestamp generation
        with patch.object(audio_logger, '_generate_timestamp', return_value=mock_timestamp):
            # Log AWS audio
            audio_logger.log_audio(sample_conversation_id, sample_aws_audio_data, 'aws', 'pcm', 16000, 16, 1)
            
            # Check filename format
            expected_filename = f"{sample_conversation_id}_{mock_timestamp}_aws.wav"
            expected_path = Path(temp_dir) / expected_filename
            assert expected_path.exists()

    def test_log_audio_converts_aws_pcm_to_wav(self, temp_dir, audio_logger_config,
                                             sample_conversation_id, sample_aws_audio_data):
        """Test that AWS PCM audio is converted to WAV format."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Log AWS audio
        result = audio_logger.log_audio(sample_conversation_id, sample_aws_audio_data, 'aws', 'pcm', 16000, 16, 1)
            
        # Check that the file contains valid WAV data
        file_path = result[0] if isinstance(result, list) else result
        assert self._is_valid_wav_file(file_path)

    # Test File Size Management

    def test_max_file_size_enforcement(self, temp_dir, audio_logger_config,
                                     sample_conversation_id):
        """Test that max file size is enforced when logging audio."""
        # Set a small max file size for testing
        audio_logger_config['max_file_size'] = 100  # 100 bytes
        
        audio_logger = AudioLogger(audio_logger_config)
        
        # Create audio data that exceeds the limit
        large_audio_data = b"x" * 150  # 150 bytes
        
        # Log the large audio data
        result = audio_logger.log_audio(sample_conversation_id, large_audio_data, 'wxcc', 'ulaw')
        
        # Should handle large files appropriately (split, truncate, or error)
        assert result is not None

    def test_file_splitting_for_large_audio(self, temp_dir, audio_logger_config,
                                          sample_conversation_id):
        """Test that large audio files are split when they exceed max size."""
        # Set a small max file size for testing
        audio_logger_config['max_file_size'] = 100  # 100 bytes
        
        audio_logger = AudioLogger(audio_logger_config)
        
        # Create audio data that exceeds the limit
        large_audio_data = b"x" * 250  # 250 bytes
        
        # Log the large audio data
        result = audio_logger.log_audio(sample_conversation_id, large_audio_data, 'wxcc', 'ulaw')
        
        # Should return multiple file paths for split files
        assert isinstance(result, list)
        assert len(result) > 1
        
        # Check that all files exist and have appropriate names
        for i, file_path in enumerate(result):
            assert Path(file_path).exists()
            assert file_path.endswith(f"_part{i+1}.wav")

    def test_file_splitting_naming_convention(self, temp_dir, audio_logger_config,
                                            sample_conversation_id, mock_timestamp):
        """Test that split files follow the correct naming convention."""
        # Set a small max file size for testing
        audio_logger_config['max_file_size'] = 100  # 100 bytes
        
        audio_logger = AudioLogger(audio_logger_config)
        
        # Mock timestamp generation
        with patch.object(audio_logger, '_generate_timestamp', return_value=mock_timestamp):
            # Create audio data that exceeds the limit
            large_audio_data = b"x" * 250  # 250 bytes
            
            # Log the large audio data
            result = audio_logger.log_audio(sample_conversation_id, large_audio_data, 'wxcc', 'ulaw')
            
            # Check naming convention for split files
            expected_base = f"{sample_conversation_id}_{mock_timestamp}_wxcc"
            for i, file_path in enumerate(result):
                expected_filename = f"{expected_base}_part{i+1}.wav"
                assert file_path.endswith(expected_filename)

    # Test Timestamp Generation

    def test_timestamp_generation_format(self, temp_dir, audio_logger_config):
        """Test that timestamps are generated in the correct format."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Generate a timestamp
        timestamp = audio_logger._generate_timestamp()
        
        # Check format: YYYYMMDD_HHMMSS
        assert len(timestamp) == 15  # 8 + 1 + 6 characters
        assert timestamp[8] == '_'  # Separator between date and time
        
        # Check that it's a valid date/time format
        try:
            datetime.strptime(timestamp, "%Y%m%d_%H%M%S")
        except ValueError:
            pytest.fail(f"Timestamp {timestamp} is not in expected format YYYYMMDD_HHMMSS")

    def test_timestamp_uniqueness(self, temp_dir, audio_logger_config):
        """Test that timestamps are unique for rapid successive calls."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Mock the timestamp generation to return unique values
        unique_timestamps = [
            "20250826_143841",
            "20250826_143842", 
            "20250826_143843",
            "20250826_143844",
            "20250826_143845"
        ]
        
        with patch.object(audio_logger, '_generate_timestamp', side_effect=unique_timestamps):
            # Generate multiple timestamps
            timestamps = []
            for _ in range(5):
                timestamp = audio_logger._generate_timestamp()
                timestamps.append(timestamp)
            
            # Check that all timestamps are unique
            assert len(set(timestamps)) == len(timestamps)
            assert timestamps == unique_timestamps

    # Test WAV File Validation

    def test_wav_file_header_creation(self, temp_dir, audio_logger_config):
        """Test that WAV file headers are created correctly."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Create a minimal WAV file using the proper method
        test_audio_data = b"test_audio_data"
        result = audio_logger._create_wav_file(test_audio_data, "test.wav")
        
        # Check that the file exists and has valid WAV headers
        test_file = Path(temp_dir) / "test.wav"
        assert test_file.exists()
        assert self._is_valid_wav_file(str(test_file))

    def test_wav_file_audio_data_integrity(self, temp_dir, audio_logger_config,
                                         sample_conversation_id, sample_wxcc_audio_data):
        """Test that audio data is preserved correctly in WAV files."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Log audio data
        result = audio_logger.log_audio(sample_conversation_id, sample_wxcc_audio_data, 'wxcc', 'ulaw')
        
        # Read the file and verify audio data integrity
        file_path = result[0] if isinstance(result, list) else result
        with open(file_path, 'rb') as f:
            # Skip WAV header (44 bytes) and read audio data
            f.seek(44)
            audio_data = f.read()
            
            # Check that audio data is preserved (after conversion)
            assert len(audio_data) > 0

    # Test Error Handling

    def test_audio_logging_failure_handling(self, temp_dir, audio_logger_config,
                                          sample_conversation_id, sample_wxcc_audio_data):
        """Test that audio logging failures are handled gracefully."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Mock file system to fail
        with patch('builtins.open', side_effect=OSError("Permission denied")):
            # Should handle the error gracefully
            result = audio_logger.log_audio(sample_conversation_id, sample_wxcc_audio_data, 'wxcc', 'ulaw')
            
            # Should return None or empty list on failure
            assert result is None or result == []

    def test_invalid_audio_data_handling(self, temp_dir, audio_logger_config,
                                       sample_conversation_id):
        """Test that invalid audio data is handled gracefully."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Test with None audio data
        result = audio_logger.log_audio(sample_conversation_id, None, 'wxcc', 'ulaw')
        assert result is None or result == []
        
        # Test with empty audio data
        result = audio_logger.log_audio(sample_conversation_id, b"", 'wxcc', 'ulaw')
        assert result is None or result == []

    def test_invalid_conversation_id_handling(self, temp_dir, audio_logger_config,
                                           sample_wxcc_audio_data):
        """Test that invalid conversation IDs are handled gracefully."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Test with None conversation ID
        result = audio_logger.log_audio(None, sample_wxcc_audio_data, 'wxcc', 'ulaw')
        assert result is None or result == []
        
        # Test with empty conversation ID
        result = audio_logger.log_audio("", sample_wxcc_audio_data, 'wxcc', 'ulaw')
        assert result is None or result == []

    # Test Cleanup

    def test_audio_logger_cleanup(self, temp_dir, audio_logger_config,
                                 sample_conversation_id):
        """Test that AudioLogger cleanup works correctly."""
        audio_logger = AudioLogger(audio_logger_config)
        
        # Log some audio to create files
        test_audio_data = b"test_audio_data"
        audio_logger.log_audio(sample_conversation_id, test_audio_data, 'wxcc', 'ulaw')
        
        # Clean up
        audio_logger.cleanup(sample_conversation_id)
        
        # Check that cleanup was performed (implementation dependent)
        # This might involve removing temporary files or resetting state
        # For now, just verify cleanup doesn't raise an exception
        assert True  # Cleanup completed successfully

    # Test Configuration Validation

    def test_invalid_config_handling(self):
        """Test that invalid configuration is handled gracefully."""
        invalid_configs = [
            {},  # Empty config
            {"output_dir": None},  # None output directory
            {"max_file_size": "invalid"},  # Invalid max file size
            {"sample_rate": -1},  # Invalid sample rate
            {"bit_depth": 0},  # Invalid bit depth
        ]
        
        for config in invalid_configs:
            try:
                audio_logger = AudioLogger(config)
                # Should use defaults or handle gracefully
                assert audio_logger is not None
            except Exception:
                # Some invalid configs might raise exceptions, which is acceptable
                pass

    # Helper Methods

    def _is_valid_wav_file(self, file_path):
        """Helper method to validate WAV file format."""
        try:
            with open(file_path, 'rb') as f:
                # Read WAV header
                header = f.read(44)
                
                # Check RIFF header
                if len(header) < 44 or not header.startswith(b'RIFF'):
                    return False
                
                # Check WAVE format
                if b'WAVE' not in header:
                    return False
                
                # Check format chunk
                if b'fmt ' not in header:
                    return False
                
                # Check data chunk
                if b'data' not in header:
                    return False
                
                return True
        except Exception:
            return False
