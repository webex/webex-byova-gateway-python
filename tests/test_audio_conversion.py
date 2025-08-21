"""
Unit tests for audio conversion functionality.

These tests ensure that the audio conversion utilities work correctly
and maintain WxCC compatibility (8kHz, 8-bit u-law, mono).
"""

import pytest
import struct
import tempfile
import wave
from pathlib import Path

from src.utils.audio_utils import AudioConverter, convert_aws_lex_audio_to_wxcc


class TestAudioConversion:
    """Test cases for audio conversion functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.converter = AudioConverter()
        
        # Create test PCM data (16kHz, 16-bit, mono)
        # Generate a simple sine wave pattern for testing
        self.test_pcm_16khz_16bit = self._generate_test_pcm_data(16000, 16, 1, 0.1)
        
        # Create test PCM data (8kHz, 8-bit, mono)
        self.test_pcm_8khz_8bit = self._generate_test_pcm_data(8000, 8, 1, 0.1)

    def _generate_test_pcm_data(self, sample_rate: int, bit_depth: int, channels: int, duration: float) -> bytes:
        """Generate test PCM audio data."""
        import math
        
        num_samples = int(sample_rate * duration)
        bytes_per_sample = bit_depth // 8
        
        if bit_depth == 16:
            # Generate 16-bit signed PCM data
            samples = []
            for i in range(num_samples):
                # Simple sine wave at 440 Hz
                sample = int(16384 * math.sin(2 * math.pi * 440 * i / sample_rate))
                samples.append(sample)
            return struct.pack(f"<{len(samples)}h", *samples)
        else:
            # Generate 8-bit unsigned PCM data
            samples = []
            for i in range(num_samples):
                # Simple sine wave at 440 Hz, offset to unsigned range
                sample = int(128 + 64 * math.sin(2 * math.pi * 440 * i / sample_rate))
                samples.append(sample)
            return struct.pack(f"<{len(samples)}B", *samples)

    def test_pcm_to_ulaw_conversion(self):
        """Test PCM to u-law conversion."""
        # Test 16-bit PCM to u-law
        ulaw_data = self.converter.pcm_to_ulaw(self.test_pcm_16khz_16bit, 8000, 16)
        
        assert len(ulaw_data) == len(self.test_pcm_16khz_16bit) // 2  # 16-bit to 8-bit
        assert all(0 <= byte <= 255 for byte in ulaw_data)  # Valid u-law range
        
        # Test 8-bit PCM to u-law
        ulaw_data_8bit = self.converter.pcm_to_ulaw(self.test_pcm_8khz_8bit, 8000, 8)
        
        assert len(ulaw_data_8bit) == len(self.test_pcm_8khz_8bit)  # Same length for 8-bit
        assert all(0 <= byte <= 255 for byte in ulaw_data_8bit)  # Valid u-law range

    def test_pcm_to_wav_conversion_ulaw(self):
        """Test PCM to WAV conversion with u-law encoding."""
        # Convert test PCM data to WAV with u-law encoding
        wav_data = self.converter.pcm_to_wav(
            self.test_pcm_8khz_8bit,
            sample_rate=8000,
            bit_depth=8,
            channels=1,
            encoding="ulaw"
        )
        
        # Verify WAV header structure
        assert wav_data.startswith(b'RIFF')
        assert b'WAVE' in wav_data
        assert b'fmt ' in wav_data
        assert b'data' in wav_data
        
        # Verify WAV file structure by parsing the header
        # RIFF chunk size (bytes 4-7)
        riff_size = struct.unpack('<I', wav_data[4:8])[0]
        
        # Format chunk size (bytes 16-19)
        fmt_size = struct.unpack('<I', wav_data[16:20])[0]
        
        # Data chunk size (bytes 40-43)
        data_size = struct.unpack('<I', wav_data[40:44])[0]
        
        # Verify the structure is correct
        assert fmt_size == 16  # Standard format chunk size
        assert data_size == len(self.test_pcm_8khz_8bit)  # Data size should match input
        
        # Verify format chunk (bytes 20-21 should be format code 7 for u-law)
        format_code = struct.unpack('<H', wav_data[20:22])[0]
        assert format_code == 7  # WAVE_FORMAT_MULAW
        
        # Verify sample rate (bytes 24-27 should be 8000)
        sample_rate = struct.unpack('<I', wav_data[24:28])[0]
        assert sample_rate == 8000
        
        # Verify bit depth (bytes 34-35 should be 8)
        bit_depth = struct.unpack('<H', wav_data[34:36])[0]
        assert bit_depth == 8
        
        # Verify channels (bytes 22-23 should be 1)
        channels = struct.unpack('<H', wav_data[22:24])[0]
        assert channels == 1

    def test_pcm_to_wav_conversion_pcm(self):
        """Test PCM to WAV conversion with PCM encoding."""
        # Convert test PCM data to WAV with PCM encoding
        wav_data = self.converter.pcm_to_wav(
            self.test_pcm_8khz_8bit,
            sample_rate=8000,
            bit_depth=8,
            channels=1,
            encoding="pcm"
        )
        
        # Verify format chunk (bytes 20-21 should be format code 1 for PCM)
        format_code = struct.unpack('<H', wav_data[20:22])[0]
        assert format_code == 1  # WAVE_FORMAT_PCM

    def test_resample_16khz_to_8khz(self):
        """Test resampling from 16kHz to 8kHz."""
        resampled_data = self.converter.resample_16khz_to_8khz(self.test_pcm_16khz_16bit, 16)
        
        # Verify resampled data is half the size (every other sample)
        assert len(resampled_data) == len(self.test_pcm_16khz_16bit) // 2
        
        # Verify the data is still valid 16-bit PCM
        assert len(resampled_data) % 2 == 0  # Even number of bytes for 16-bit

    def test_convert_aws_lex_audio_to_wxcc(self):
        """Test complete AWS Lex to WxCC conversion."""
        # Test the standalone function
        wav_audio, content_type = convert_aws_lex_audio_to_wxcc(
            self.test_pcm_16khz_16bit, 
            bit_depth=16
        )
        
        assert content_type == "audio/wav"
        assert len(wav_audio) > 0
        
        # Verify WAV header structure
        assert wav_audio.startswith(b'RIFF')
        assert b'WAVE' in wav_audio
        assert b'fmt ' in wav_audio
        assert b'data' in wav_audio
        
        # Verify format is u-law (WxCC requirement)
        format_code = struct.unpack('<H', wav_audio[20:22])[0]
        assert format_code == 7  # WAVE_FORMAT_MULAW
        
        # Verify WxCC-compatible format
        sample_rate = struct.unpack('<I', wav_audio[24:28])[0]
        bit_depth = struct.unpack('<H', wav_audio[34:36])[0]
        channels = struct.unpack('<H', wav_audio[22:24])[0]
        
        assert sample_rate == 8000  # WxCC requirement
        assert bit_depth == 8       # WxCC requirement
        assert channels == 1        # WxCC requirement

    def test_convert_aws_lex_audio_to_wxcc_with_logger(self):
        """Test AWS Lex to WxCC conversion with logger parameter."""
        import logging
        
        logger = logging.getLogger(__name__)
        wav_audio, content_type = convert_aws_lex_audio_to_wxcc(
            self.test_pcm_16khz_16bit, 
            bit_depth=16,
            logger=logger
        )
        
        assert content_type == "audio/wav"
        assert len(wav_audio) > 0

    def test_wav_file_validity(self):
        """Test that generated WAV files are valid and can be opened."""
        # Convert to WAV
        wav_data = self.converter.pcm_to_wav(
            self.test_pcm_8khz_8bit,
            sample_rate=8000,
            bit_depth=8,
            channels=1,
            encoding="ulaw"
        )
        
        # Write to temporary file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_file.write(wav_data)
            temp_file_path = temp_file.name
        
        try:
            # For u-law format, we can't use the wave module directly as it doesn't support format 7
            # Instead, verify the WAV header structure manually
            
            # Check RIFF header
            assert wav_data.startswith(b'RIFF')
            assert b'WAVE' in wav_data
            
            # Check format chunk
            assert b'fmt ' in wav_data
            
            # Check data chunk
            assert b'data' in wav_data
            
            # Verify format code is 7 (u-law)
            format_code = struct.unpack('<H', wav_data[20:22])[0]
            assert format_code == 7
            
            # Verify other header values
            sample_rate = struct.unpack('<I', wav_data[24:28])[0]
            assert sample_rate == 8000
            
            channels = struct.unpack('<H', wav_data[22:24])[0]
            assert channels == 1
            
            bit_depth = struct.unpack('<H', wav_data[34:36])[0]
            assert bit_depth == 8
            
            # Verify data chunk size matches audio data
            data_size = struct.unpack('<I', wav_data[40:44])[0]
            assert data_size == len(self.test_pcm_8khz_8bit)
            
        finally:
            # Clean up
            Path(temp_file_path).unlink(missing_ok=True)

    def test_error_handling_invalid_data(self):
        """Test error handling with invalid audio data."""
        # Test with empty data
        result = self.converter.pcm_to_ulaw(b"", 8000, 16)
        assert result == b""  # Should return empty data on error
        
        # Test with invalid bit depth
        result = self.converter.pcm_to_ulaw(self.test_pcm_16khz_16bit, 8000, 24)
        assert result == self.test_pcm_16khz_16bit  # Should return original data on error
        
        # Test with invalid encoding
        result = self.converter.pcm_to_wav(
            self.test_pcm_8khz_8bit,
            sample_rate=8000,
            bit_depth=8,
            channels=1,
            encoding="invalid"
        )
        assert result == self.test_pcm_8khz_8bit  # Should return original data on error

    def test_wxcc_compatibility_validation(self):
        """Test that converted audio meets WxCC requirements."""
        wav_audio, content_type = convert_aws_lex_audio_to_wxcc(
            self.test_pcm_16khz_16bit, 
            bit_depth=16
        )
        
        # Extract WAV header information
        sample_rate = struct.unpack('<I', wav_audio[24:28])[0]
        bit_depth = struct.unpack('<H', wav_audio[34:36])[0]
        channels = struct.unpack('<H', wav_audio[22:24])[0]
        format_code = struct.unpack('<H', wav_audio[20:22])[0]
        
        # Verify WxCC compatibility requirements
        assert sample_rate == 8000, f"Sample rate must be 8000 Hz, got {sample_rate}"
        assert bit_depth == 8, f"Bit depth must be 8, got {bit_depth}"
        assert channels == 1, f"Channels must be 1, got {channels}"
        assert format_code == 7, f"Encoding must be u-law (7), got {format_code}"
        
        # Verify content type
        assert content_type == "audio/wav", f"Content type must be 'audio/wav', got {content_type}"

    def test_audio_conversion_pipeline(self):
        """Test the complete audio conversion pipeline."""
        # Step 1: Resample 16kHz to 8kHz
        pcm_8khz = self.converter.resample_16khz_to_8khz(self.test_pcm_16khz_16bit, 16)
        assert len(pcm_8khz) == len(self.test_pcm_16khz_16bit) // 2
        
        # Step 2: Convert to u-law
        ulaw_audio = self.converter.pcm_to_ulaw(pcm_8khz, 8000, 16)
        assert len(ulaw_audio) == len(pcm_8khz) // 2  # 16-bit to 8-bit
        
        # Step 3: Convert to WAV
        wav_audio = self.converter.pcm_to_wav(
            ulaw_audio,
            sample_rate=8000,
            bit_depth=8,
            channels=1,
            encoding="ulaw"
        )
        
        # Verify final result
        assert wav_audio.startswith(b'RIFF')
        
        # Verify WAV file structure by parsing the header
        # Data chunk size (bytes 40-43)
        data_size = struct.unpack('<I', wav_audio[40:44])[0]
        assert data_size == len(ulaw_audio)  # Data size should match u-law data
        
        # Verify WxCC compatibility
        sample_rate = struct.unpack('<I', wav_audio[24:28])[0]
        bit_depth = struct.unpack('<H', wav_audio[34:36])[0]
        channels = struct.unpack('<H', wav_audio[22:24])[0]
        format_code = struct.unpack('<H', wav_audio[20:22])[0]
        
        assert sample_rate == 8000
        assert bit_depth == 8
        assert channels == 1
        assert format_code == 7
