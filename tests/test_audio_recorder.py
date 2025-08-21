"""
Unit tests for the AudioRecorder class.

These tests ensure the AudioRecorder works correctly for audio recording
when integrated with AudioBuffer for audio data management.
"""

import pytest
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from src.utils.audio_buffer import AudioBuffer
from src.utils.audio_recorder import AudioRecorder


class TestAudioRecorder:
    """Test cases for AudioRecorder class."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def mock_audio_buffer(self):
        """Create a mock AudioBuffer instance for testing."""
        buffer = Mock(spec=AudioBuffer)
        buffer.conversation_id = "test_conv_123"
        buffer.get_buffer_size.return_value = 0
        buffer.get_buffered_audio.return_value = None
        buffer.get_buffering_stats.return_value = {
            "conversation_id": "test_conv_123",
            "is_buffering": False,
            "waiting_for_speech": True,
            "speech_detected": False,
            "buffer_size": 0,
            "max_buffer_size": 1024*1024,
            "buffer_utilization": 0.0,
            "last_audio_time": 0,
            "silence_threshold": 3000,
            "silence_duration": 2.0,
            "quiet_threshold": 20,
            "sample_rate": 8000,
            "bit_depth": 8,
            "channels": 1,
            "encoding": "ulaw"
        }
        return buffer

    @pytest.fixture
    def basic_recorder(self, temp_dir, mock_audio_buffer):
        """Create a basic AudioRecorder instance for testing."""
        return AudioRecorder(
            conversation_id="test_conv_123",
            audio_buffer=mock_audio_buffer,
            output_dir=temp_dir,
            logger=Mock()
        )

    def test_initialization_default_values(self, temp_dir, mock_audio_buffer):
        """Test AudioRecorder initialization with default values."""
        recorder = AudioRecorder("test_conv_456", mock_audio_buffer, temp_dir)
        
        assert recorder.conversation_id == "test_conv_456"
        assert recorder.audio_buffer == mock_audio_buffer
        assert recorder.output_dir == Path(temp_dir)
        assert recorder.sample_rate == 8000
        assert recorder.bit_depth == 8
        assert recorder.channels == 1
        assert recorder.encoding == "ulaw"
        assert recorder.wav_file is None
        assert not recorder.recording
        assert recorder.file_path is None

    def test_initialization_custom_values(self, temp_dir, mock_audio_buffer):
        """Test AudioRecorder initialization with custom values."""
        recorder = AudioRecorder(
            conversation_id="test_conv",
            audio_buffer=mock_audio_buffer,
            output_dir=temp_dir,
            sample_rate=16000,
            bit_depth=16,
            channels=2,
            encoding="pcm",
            logger=Mock()
        )
        
        assert recorder.conversation_id == "test_conv"
        assert recorder.audio_buffer == mock_audio_buffer
        assert recorder.output_dir == Path(temp_dir)
        assert recorder.sample_rate == 16000
        assert recorder.bit_depth == 16
        assert recorder.channels == 2
        assert recorder.encoding == "pcm"

    def test_start_recording_new_session(self, basic_recorder, temp_dir):
        """Test starting a new recording session."""
        basic_recorder.start_recording()
        
        assert basic_recorder.recording
        assert basic_recorder.file_path is not None
        assert basic_recorder.file_path.parent == Path(temp_dir)
        assert basic_recorder.file_path.name.startswith("caller_audio_test_conv_123_")
        assert basic_recorder.file_path.name.endswith(".wav")

    def test_start_recording_finalizes_previous(self, basic_recorder, temp_dir):
        """Test that starting recording finalizes previous session."""
        # Start first recording
        basic_recorder.start_recording()
        basic_recorder.recording = True
        
        # Start second recording
        basic_recorder.start_recording()
        
        assert basic_recorder.recording
        assert basic_recorder.file_path is not None

    def test_start_recording_ulaw_format(self, basic_recorder, temp_dir):
        """Test starting recording with u-law format."""
        basic_recorder.encoding = "ulaw"
        basic_recorder.start_recording()
        
        assert basic_recorder.recording
        assert basic_recorder._wav_file_handle is not None
        assert basic_recorder.wav_file is None

    def test_start_recording_pcm_format(self, basic_recorder, temp_dir):
        """Test starting recording with PCM format."""
        basic_recorder.encoding = "pcm"
        basic_recorder.start_recording()
        
        assert basic_recorder.recording
        assert basic_recorder.wav_file is not None
        # PCM format doesn't use _wav_file_handle, it uses the standard wave module

    def test_add_audio_data_empty(self, basic_recorder):
        """Test adding empty audio data."""
        result = basic_recorder.add_audio_data(b"", "ulaw")
        
        assert result is True

    def test_add_audio_data_delegates_to_buffer(self, basic_recorder, mock_audio_buffer):
        """Test that add_audio_data delegates to AudioBuffer."""
        test_audio = b"test audio data"
        mock_audio_buffer.add_audio_data.return_value = True
        
        result = basic_recorder.add_audio_data(test_audio, "ulaw")
        
        assert result is True
        mock_audio_buffer.add_audio_data.assert_called_once_with(test_audio, "ulaw")

    def test_add_audio_data_silence_detected_finalizes_recording(self, basic_recorder, mock_audio_buffer):
        """Test that silence detection finalizes recording."""
        test_audio = b"test audio data"
        mock_audio_buffer.add_audio_data.return_value = False  # Silence detected
        basic_recorder.recording = True
        
        result = basic_recorder.add_audio_data(test_audio, "ulaw")
        
        assert result is False
        assert not basic_recorder.recording

    def test_add_audio_data_writes_to_wav_file_when_recording(self, basic_recorder, mock_audio_buffer):
        """Test that audio data is written to WAV file when recording."""
        test_audio = b"test audio data"
        mock_audio_buffer.add_audio_data.return_value = True
        mock_audio_buffer.get_buffer_size.return_value = 100
        mock_audio_buffer.get_buffered_audio.return_value = test_audio
        basic_recorder.recording = True
        
        # Mock the WAV file writing
        with patch.object(basic_recorder, '_write_ulaw_audio_data') as mock_write:
            basic_recorder.encoding = "ulaw"
            basic_recorder._wav_file_handle = Mock()
            
            result = basic_recorder.add_audio_data(test_audio, "ulaw")
            
            assert result is True
            mock_write.assert_called_once_with(test_audio)

    def test_check_silence_timeout_delegates_to_buffer(self, basic_recorder, mock_audio_buffer):
        """Test that check_silence_timeout delegates to AudioBuffer."""
        mock_audio_buffer.check_silence_timeout.return_value = True
        
        result = basic_recorder.check_silence_timeout()
        
        assert result is True
        mock_audio_buffer.check_silence_timeout.assert_called_once()

    def test_check_silence_timeout_silence_detected_finalizes_recording(self, basic_recorder, mock_audio_buffer):
        """Test that silence timeout detection finalizes recording."""
        mock_audio_buffer.check_silence_timeout.return_value = False  # Silence detected
        basic_recorder.recording = True
        
        result = basic_recorder.check_silence_timeout()
        
        assert result is False
        assert not basic_recorder.recording

    def test_finalize_recording_not_recording(self, basic_recorder):
        """Test finalizing recording when not recording."""
        result = basic_recorder.finalize_recording()
        
        assert result is None

    def test_finalize_recording_with_remaining_data(self, basic_recorder, mock_audio_buffer):
        """Test finalizing recording with remaining data in buffer."""
        basic_recorder.recording = True
        basic_recorder.encoding = "ulaw"
        basic_recorder._wav_file_handle = Mock()
        basic_recorder.file_path = Path("/test/path/file.wav")  # Set file path
        mock_audio_buffer.get_buffer_size.return_value = 100
        mock_audio_buffer.get_buffered_audio.return_value = b"remaining data"
        
        with patch.object(basic_recorder, '_write_ulaw_audio_data') as mock_write:
            result = basic_recorder.finalize_recording()
            
            assert result is not None
            mock_write.assert_called_once_with(b"remaining data")

    def test_finalize_recording_closes_ulaw_file(self, basic_recorder):
        """Test that finalizing recording closes u-law WAV file."""
        basic_recorder.recording = True
        basic_recorder.encoding = "ulaw"
        basic_recorder._wav_file_handle = Mock()
        
        with patch.object(basic_recorder, '_close_ulaw_wav_file') as mock_close:
            basic_recorder.finalize_recording()
            
            mock_close.assert_called_once()

    def test_finalize_recording_closes_pcm_file(self, basic_recorder):
        """Test that finalizing recording closes PCM WAV file."""
        basic_recorder.recording = True
        basic_recorder.encoding = "pcm"
        mock_wav_file = Mock()
        basic_recorder.wav_file = mock_wav_file
        basic_recorder.file_path = Path("/test/path/file.wav")  # Set file path
        
        basic_recorder.finalize_recording()
        
        mock_wav_file.close.assert_called_once()

    def test_is_recording(self, basic_recorder):
        """Test recording status check."""
        assert not basic_recorder.is_recording()
        
        basic_recorder.recording = True
        assert basic_recorder.is_recording()

    def test_get_recording_path(self, basic_recorder):
        """Test getting recording file path."""
        assert basic_recorder.get_recording_path() is None
        
        basic_recorder.file_path = Path("/test/path/file.wav")
        assert basic_recorder.get_recording_path() == "/test/path/file.wav"

    def test_get_recording_stats(self, basic_recorder, mock_audio_buffer):
        """Test getting recording statistics."""
        stats = basic_recorder.get_recording_stats()
        
        assert "conversation_id" in stats
        assert "is_recording" in stats
        assert "file_path" in stats
        assert "output_dir" in stats
        assert "sample_rate" in stats
        assert "bit_depth" in stats
        assert "channels" in stats
        assert "encoding" in stats
        assert "buffer_stats" in stats

    def test_stop_recording(self, basic_recorder):
        """Test stopping recording."""
        basic_recorder.recording = True
        
        with patch.object(basic_recorder, 'finalize_recording') as mock_finalize:
            mock_finalize.return_value = "/test/path/file.wav"
            
            result = basic_recorder.stop_recording()
            
            assert result == "/test/path/file.wav"
            mock_finalize.assert_called_once()

    def test_pause_recording_not_implemented(self, basic_recorder):
        """Test that pause recording is not implemented."""
        with patch.object(basic_recorder.logger, 'warning') as mock_warning:
            basic_recorder.pause_recording()
            
            mock_warning.assert_called_once_with("Pause recording not implemented in current version")

    def test_resume_recording_not_implemented(self, basic_recorder):
        """Test that resume recording is not implemented."""
        with patch.object(basic_recorder.logger, 'warning') as mock_warning:
            basic_recorder.resume_recording()
            
            mock_warning.assert_called_once_with("Resume recording not implemented in current version")

    def test_create_ulaw_wav_file_success(self, basic_recorder, temp_dir):
        """Test successful u-law WAV file creation."""
        file_path = os.path.join(temp_dir, "test.wav")
        
        basic_recorder._create_ulaw_wav_file(file_path)
        
        assert basic_recorder._wav_file_handle is not None
        assert basic_recorder._data_start_pos > 0
        assert basic_recorder._riff_size_pos == 4

    def test_create_ulaw_wav_file_failure(self, basic_recorder, temp_dir):
        """Test u-law WAV file creation failure."""
        # Try to create file in non-existent directory
        file_path = "/non/existent/path/test.wav"
        
        with pytest.raises(Exception):
            basic_recorder._create_ulaw_wav_file(file_path)
        
        assert basic_recorder._wav_file_handle is None

    def test_write_ulaw_audio_data_success(self, basic_recorder):
        """Test successful u-law audio data writing."""
        mock_handle = Mock()
        mock_handle.tell.return_value = 100  # Return a fixed position
        basic_recorder._wav_file_handle = mock_handle
        basic_recorder._data_start_pos = 44
        basic_recorder._riff_size_pos = 4
        
        test_audio = b"test audio data"
        
        basic_recorder._write_ulaw_audio_data(test_audio)
        
        mock_handle.write.assert_called()
        mock_handle.flush.assert_called()

    def test_write_ulaw_audio_data_no_handle(self, basic_recorder):
        """Test u-law audio data writing when no file handle exists."""
        test_audio = b"test audio data"
        
        with patch.object(basic_recorder.logger, 'error') as mock_error:
            basic_recorder._write_ulaw_audio_data(test_audio)
            
            mock_error.assert_called_once_with("No u-law WAV file handle available for writing")

    def test_close_ulaw_wav_file_success(self, basic_recorder):
        """Test successful u-law WAV file closing."""
        mock_handle = Mock()
        basic_recorder._wav_file_handle = mock_handle
        
        basic_recorder._close_ulaw_wav_file()
        
        mock_handle.close.assert_called_once()
        assert basic_recorder._wav_file_handle is None

    def test_close_ulaw_wav_file_no_handle(self, basic_recorder):
        """Test u-law WAV file closing when no handle exists."""
        # Should not raise an exception
        basic_recorder._close_ulaw_wav_file()

    def test_integration_with_audio_buffer(self, temp_dir):
        """Test integration between AudioRecorder and AudioBuffer."""
        # Create a real AudioBuffer
        audio_buffer = AudioBuffer(
            conversation_id="test_conv",
            silence_threshold=3000,
            silence_duration=0.1,  # Short duration for testing
            quiet_threshold=20,
            logger=Mock()
        )
        
        # Create AudioRecorder with the buffer
        recorder = AudioRecorder(
            conversation_id="test_conv",
            audio_buffer=audio_buffer,
            output_dir=temp_dir,
            logger=Mock()
        )
        
        # Start recording
        recorder.start_recording()
        assert recorder.recording
        
        # Add some audio data
        test_audio = b"test audio data"
        result = recorder.add_audio_data(test_audio, "ulaw")
        
        # Should continue recording
        assert result is True
        assert recorder.recording
        
        # Finalize recording
        file_path = recorder.finalize_recording()
        assert file_path is not None
        assert not recorder.recording
