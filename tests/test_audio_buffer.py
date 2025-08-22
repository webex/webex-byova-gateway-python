"""
Unit tests for the AudioBuffer class.

These tests ensure the AudioBuffer works correctly for audio buffering
and silence detection functionality.
"""

import pytest
import tempfile
import os
import time
from unittest.mock import Mock, patch

from src.utils.audio_buffer import AudioBuffer


class TestAudioBuffer:
    """Test cases for AudioBuffer class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def basic_buffer(self, temp_dir):
        """Create a basic AudioBuffer instance for testing."""
        return AudioBuffer(
            conversation_id="test_conv_123",
            max_buffer_size=1024*1024,  # 1MB
            silence_threshold=3000,
            silence_duration=2.0,
            quiet_threshold=20,
            logger=Mock()
        )

    def test_initialization_default_values(self, temp_dir):
        """Test AudioBuffer initialization with default values."""
        buffer = AudioBuffer("test_conv_456")
        
        assert buffer.conversation_id == "test_conv_456"
        assert buffer.max_buffer_size == 1024*1024  # 1MB default
        assert buffer.silence_threshold == 3000
        assert buffer.silence_duration == 2.0
        assert buffer.quiet_threshold == 20
        assert buffer.sample_rate == 8000
        assert buffer.bit_depth == 8
        assert buffer.channels == 1
        assert buffer.encoding == "ulaw"

        assert buffer.audio_buffer == bytearray()
        assert not buffer.buffering
        assert buffer.waiting_for_speech
        assert not buffer.speech_detected

    def test_initialization_custom_values(self, temp_dir):
        """Test AudioBuffer initialization with custom values."""
        buffer = AudioBuffer(
            conversation_id="test_conv",
            max_buffer_size=512*1024,  # 512KB
            silence_threshold=5000,
            silence_duration=1.5,
            quiet_threshold=15,
            sample_rate=16000,
            bit_depth=16,
            channels=2,
            encoding="pcm",
            logger=Mock()
        )
        
        assert buffer.conversation_id == "test_conv"
        assert buffer.max_buffer_size == 512*1024
        assert buffer.silence_threshold == 5000
        assert buffer.silence_duration == 1.5
        assert buffer.quiet_threshold == 15
        assert buffer.sample_rate == 16000
        assert buffer.bit_depth == 16
        assert buffer.channels == 2
        assert buffer.encoding == "pcm"


    def test_start_buffering(self, basic_buffer):
        """Test starting a buffering session."""
        basic_buffer.start_buffering()
        
        assert basic_buffer.buffering
        assert basic_buffer.last_audio_time > 0
        assert basic_buffer.waiting_for_speech
        assert not basic_buffer.speech_detected
        assert len(basic_buffer.audio_buffer) == 0

    def test_start_buffering_resets_previous_session(self, basic_buffer):
        """Test that starting buffering resets previous session."""
        # Start first session
        basic_buffer.start_buffering()
        basic_buffer.audio_buffer.extend(b"test data")
        
        # Start second session
        basic_buffer.start_buffering()
        
        assert basic_buffer.buffering
        assert len(basic_buffer.audio_buffer) == 0

    def test_add_audio_data_empty(self, basic_buffer):
        """Test adding empty audio data."""
        result = basic_buffer.add_audio_data(b"", "ulaw")
        
        assert result["buffering_continues"] is True
        assert result["silence_detected"] is False
        assert len(basic_buffer.audio_buffer) == 0

    def test_add_audio_data_basic(self, basic_buffer):
        """Test adding basic audio data."""
        test_audio = b"test audio data"
        result = basic_buffer.add_audio_data(test_audio, "ulaw")
        
        assert result["buffering_continues"] is True
        assert result["silence_detected"] is False
        assert len(basic_buffer.audio_buffer) > 0

    def test_buffer_size_limit(self, basic_buffer):
        """Test that buffer respects size limits."""
        # Set a small buffer size for testing
        basic_buffer.max_buffer_size = 100
        
        # Add data that exceeds the limit
        large_audio = b"x" * 150
        result = basic_buffer.add_audio_data(large_audio, "ulaw")
        
        assert result["buffering_continues"] is True
        assert result["silence_detected"] is False
        assert len(basic_buffer.audio_buffer) <= 100

    def test_get_buffered_audio(self, basic_buffer):
        """Test getting buffered audio data."""
        test_audio = b"test audio data"
        basic_buffer.audio_buffer.extend(test_audio)
        
        result = basic_buffer.get_buffered_audio()
        assert result == test_audio

    def test_get_buffered_audio_empty(self, basic_buffer):
        """Test getting buffered audio when buffer is empty."""
        result = basic_buffer.get_buffered_audio()
        assert result is None

    def test_get_buffer_size(self, basic_buffer):
        """Test getting buffer size."""
        assert basic_buffer.get_buffer_size() == 0
        
        test_audio = b"test audio data"
        basic_buffer.audio_buffer.extend(test_audio)
        
        assert basic_buffer.get_buffer_size() == len(test_audio)

    def test_is_buffer_full(self, basic_buffer):
        """Test buffer full status."""
        assert not basic_buffer.is_buffer_full()
        
        # Set small buffer size and fill it
        basic_buffer.max_buffer_size = 10
        basic_buffer.audio_buffer.extend(b"x" * 10)
        
        assert basic_buffer.is_buffer_full()

    def test_clear_buffer(self, basic_buffer):
        """Test clearing the buffer."""
        basic_buffer.audio_buffer.extend(b"test data")
        assert len(basic_buffer.audio_buffer) > 0
        
        basic_buffer.clear_buffer()
        assert len(basic_buffer.audio_buffer) == 0

    def test_reset_buffer(self, basic_buffer):
        """Test resetting the buffer after processing audio."""
        # Manually set the buffer to buffering state to test the reset functionality
        basic_buffer.start_buffering()
        basic_buffer.audio_buffer.extend(b"test data")
        
        # Verify we're in buffering state (start_buffering puts us in waiting_for_speech mode)
        assert basic_buffer.is_buffering()
        assert basic_buffer.waiting_for_speech  # start_buffering puts us in waiting mode
        assert basic_buffer.get_buffer_size() > 0
        
        # Reset buffer
        basic_buffer.reset_buffer()
        
        # Verify we're back to waiting for speech state
        assert not basic_buffer.is_buffering()
        assert basic_buffer.waiting_for_speech
        assert not basic_buffer.speech_detected
        assert basic_buffer.get_buffer_size() == 0

    def test_stop_buffering(self, basic_buffer):
        """Test stopping buffering."""
        basic_buffer.start_buffering()
        basic_buffer.audio_buffer.extend(b"test data")
        
        basic_buffer.stop_buffering()
        
        assert not basic_buffer.buffering
        assert basic_buffer.waiting_for_speech
        assert not basic_buffer.speech_detected
        assert len(basic_buffer.audio_buffer) == 0

    def test_is_buffering(self, basic_buffer):
        """Test buffering status check."""
        assert not basic_buffer.is_buffering()
        
        basic_buffer.start_buffering()
        assert basic_buffer.is_buffering()

    def test_get_buffering_stats(self, basic_buffer):
        """Test getting buffering statistics."""
        stats = basic_buffer.get_buffering_stats()
        
        assert "conversation_id" in stats
        assert "is_buffering" in stats
        assert "waiting_for_speech" in stats
        assert "speech_detected" in stats
        assert "buffer_size" in stats
        assert "max_buffer_size" in stats
        assert "buffer_utilization" in stats
        assert "last_audio_time" in stats
        assert "silence_threshold" in stats
        assert "silence_duration" in stats
        assert "quiet_threshold" in stats
        assert "sample_rate" in stats
        assert "bit_depth" in stats
        assert "channels" in stats
        assert "encoding" in stats



    def test_get_frame_size_ulaw(self, basic_buffer):
        """Test frame size calculation for u-law encoding."""
        basic_buffer.encoding = "ulaw"
        frame_size = basic_buffer._get_frame_size()
        
        assert frame_size == 160  # 160 samples * 1 byte per sample

    def test_get_frame_size_pcm_16bit(self, basic_buffer):
        """Test frame size calculation for 16-bit PCM encoding."""
        basic_buffer.encoding = "pcm"
        basic_buffer.bit_depth = 16
        frame_size = basic_buffer._get_frame_size()
        
        assert frame_size == 320  # 160 samples * 2 bytes per sample

    def test_get_frame_size_pcm_8bit(self, basic_buffer):
        """Test frame size calculation for 8-bit PCM encoding."""
        basic_buffer.encoding = "pcm"
        basic_buffer.bit_depth = 8
        frame_size = basic_buffer._get_frame_size()
        
        assert frame_size == 160  # 160 samples * 1 byte per sample

    def test_get_frame_size_unknown_encoding(self, basic_buffer):
        """Test frame size calculation for unknown encoding."""
        basic_buffer.encoding = "unknown"
        frame_size = basic_buffer._get_frame_size()
        
        assert frame_size == 640  # Default fallback

    def test_convert_audio_to_buffer_format_same_encoding(self, basic_buffer):
        """Test audio format conversion when formats match."""
        test_audio = b"test audio data"
        result = basic_buffer._convert_audio_to_buffer_format(test_audio, "ulaw")
        
        assert result == test_audio

    def test_convert_audio_to_buffer_format_different_encoding(self, basic_buffer):
        """Test audio format conversion when formats differ."""
        test_audio = b"test audio data"
        result = basic_buffer._convert_audio_to_buffer_format(test_audio, "pcm")
        
        # Should return original data with warning (conversion not implemented yet)
        assert result == test_audio

    def test_detect_silence_empty_data(self, basic_buffer):
        """Test silence detection with empty data."""
        result = basic_buffer.detect_silence(b"")
        assert result is True

    def test_detect_silence_ulaw_silence(self, basic_buffer):
        """Test silence detection with u-law silence data."""
        # Create u-law data that represents silence (mostly 0xFF and values close to 127)
        silence_data = bytes([0xFF, 127, 0xFF, 126, 0xFF, 128, 0xFF, 127])
        result = basic_buffer.detect_silence(silence_data)
        
        assert result is True

    def test_detect_silence_ulaw_speech(self, basic_buffer):
        """Test silence detection with u-law speech data."""
        # Create u-law data that represents speech (values far from 127 and 0xFF)
        speech_data = bytes([0, 50, 100, 150, 200, 250, 1, 99])
        result = basic_buffer.detect_silence(speech_data)
        
        assert result is False

    def test_detect_silence_pcm_not_implemented(self, basic_buffer):
        """Test silence detection with PCM data (not implemented yet)."""
        basic_buffer.encoding = "pcm"
        test_audio = b"test pcm data"
        result = basic_buffer.detect_silence(test_audio)
        
        assert result is False  # Default fallback for PCM

    def test_check_silence_timeout_not_buffering(self, basic_buffer):
        """Test silence timeout check when not buffering."""
        result = basic_buffer.check_silence_timeout()
        assert result["buffering_continues"] is True
        assert result["silence_detected"] is False

    def test_check_silence_timeout_waiting_for_speech(self, basic_buffer):
        """Test silence timeout check when waiting for speech."""
        basic_buffer.waiting_for_speech = True
        result = basic_buffer.check_silence_timeout()
        assert result["buffering_continues"] is True
        assert result["silence_detected"] is False

    def test_check_silence_timeout_silence_exceeded(self, basic_buffer):
        """Test silence timeout check when silence duration is exceeded."""
        basic_buffer.start_buffering()
        basic_buffer.audio_buffer.extend(b"test data")
        
        # Set last audio time to exceed silence duration
        basic_buffer.last_audio_time = time.time() - 3.0  # 3 seconds ago
        
        result = basic_buffer.check_silence_timeout()
        
        assert result["silence_detected"] is True
        assert result["buffering_continues"] is False

    def test_check_silence_timeout_silence_not_exceeded(self, basic_buffer):
        """Test silence timeout check when silence duration is not exceeded."""
        basic_buffer.start_buffering()
        basic_buffer.audio_buffer.extend(b"test data")
        
        # Set last audio time to be within silence duration
        basic_buffer.last_audio_time = time.time() - 1.0  # 1 second ago
        
        result = basic_buffer.check_silence_timeout()
        
        assert result["silence_detected"] is False
        assert result["buffering_continues"] is True

    def test_add_audio_data_with_silence_detection(self, basic_buffer):
        """Test that adding audio data can detect silence when threshold is reached."""
        basic_buffer.start_buffering()
        
        # Add some speech data first (enough to meet frame size requirement)
        speech_data = bytes([0, 50, 100, 150, 200, 250, 1, 99] * 20)  # 160 bytes
        basic_buffer.add_audio_data(speech_data, "ulaw")
        
        # Now add silence data that should trigger silence detection
        silence_data = bytes([0xFF, 127, 0xFF, 126, 0xFF, 128, 0xFF, 127] * 20)  # 160 bytes
        
        # Set last_audio_time to a value that will exceed silence_duration when time.time() is called
        basic_buffer.last_audio_time = 0.0  # Set to 0, so any positive time will exceed 2.0s threshold
        
        result = basic_buffer.add_audio_data(silence_data, "ulaw")
        
        # Should detect silence
        assert result["silence_detected"] is True
