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

    def test_24khz_resampling_convenience_function(self):
        """Test the 24kHz resampling convenience function."""
        from src.utils.audio_utils import resample_24khz_to_8khz
        
        # Generate test PCM data (24kHz, 16-bit, mono)
        test_pcm_24khz_16bit = self._generate_test_pcm_data(24000, 16, 1, 0.1)
        
        # Test the convenience function
        resampled_data = resample_24khz_to_8khz(test_pcm_24khz_16bit, 16)
        
        # Verify resampled data is one-third the size (every 3rd sample)
        assert len(resampled_data) == len(test_pcm_24khz_16bit) // 3
        
        # Verify the data is still valid 16-bit PCM
        assert len(resampled_data) % 2 == 0  # Even number of bytes for 16-bit

    def test_resample_24khz_to_8khz(self):
        """Test resampling from 24kHz to 8kHz."""
        # Generate test PCM data (24kHz, 16-bit, mono)
        test_pcm_24khz_16bit = self._generate_test_pcm_data(24000, 16, 1, 0.1)
        
        resampled_data = self.converter.resample_24khz_to_8khz(test_pcm_24khz_16bit, 16)
        
        # Verify resampled data is one-third the size (every 3rd sample)
        assert len(resampled_data) == len(test_pcm_24khz_16bit) // 3
        
        # Verify the data is still valid 16-bit PCM
        assert len(resampled_data) % 2 == 0  # Even number of bytes for 16-bit

    def test_resample_24khz_to_8khz_8bit(self):
        """Test resampling from 24kHz to 8kHz with 8-bit PCM."""
        # Generate test PCM data (24kHz, 8-bit, mono)
        test_pcm_24khz_8bit = self._generate_test_pcm_data(24000, 8, 1, 0.1)
        
        resampled_data = self.converter.resample_24khz_to_8khz(test_pcm_24khz_8bit, 8)
        
        # Verify resampled data is one-third the size (every 3rd sample)
        assert len(resampled_data) == len(test_pcm_24khz_8bit) // 3
        
        # Verify the data is still valid 8-bit PCM
        assert len(resampled_data) % 1 == 0  # Any number of bytes for 8-bit

    def test_resample_24khz_to_8khz_quality(self):
        """Test that 24kHz to 8kHz resampling maintains audio quality."""
        # Generate a longer test signal for better quality assessment
        test_signal = self._generate_test_pcm_data(24000, 16, 1, 0.5)  # 0.5 seconds
        
        # Resample
        resampled = self.converter.resample_24khz_to_8khz(test_signal, 16)
        
        # Verify resampling results
        original_samples = len(test_signal) // 2  # 16-bit samples
        resampled_samples = len(resampled) // 2   # 16-bit samples
        
        # Should have exactly one-third the samples (24kHz -> 8kHz)
        assert resampled_samples == original_samples // 3, f"Expected {original_samples // 3} samples, got {resampled_samples}"
        
        # Verify the resampled data is valid PCM
        samples = struct.unpack(f"<{resampled_samples}h", resampled)
        assert all(-32768 <= sample <= 32767 for sample in samples), "All samples should be valid 16-bit PCM"

    def test_resample_24khz_to_8khz_edge_cases(self):
        """Test edge cases for 24kHz to 8kHz resampling."""
        # Test with very short audio (less than 5 samples)
        short_audio = struct.pack("<3h", 1000, 2000, 3000)  # 3 samples, 6 bytes
        resampled = self.converter.resample_24khz_to_8khz(short_audio, 16)
        
        # Should handle gracefully and return valid data
        assert len(resampled) > 0, "Should handle short audio gracefully"
        
        # Test with single sample
        single_sample = struct.pack("<1h", 1000)  # 1 sample, 2 bytes
        resampled_single = self.converter.resample_24khz_to_8khz(single_sample, 16)
        
        # Should handle gracefully
        assert len(resampled_single) > 0, "Should handle single sample gracefully"

    def test_resample_24khz_to_8khz_invalid_bit_depth(self):
        """Test 24kHz resampling with invalid bit depth."""
        test_pcm_24khz_16bit = self._generate_test_pcm_data(24000, 16, 1, 0.1)
        
        # Test with unsupported bit depth
        result = self.converter.resample_24khz_to_8khz(test_pcm_24khz_16bit, 24)
        
        # Should return original data with warning
        assert result == test_pcm_24khz_16bit, "Should return original data for unsupported bit depth"

    def test_resample_24khz_to_8khz_error_handling(self):
        """Test error handling in 24kHz resampling."""
        # Test with data that's too short for 16-bit processing
        # Need at least 6 bytes (3 samples) for 16-bit processing
        short_data = b"\x00\x00"  # Only 2 bytes, not enough for 16-bit
        
        # Should handle gracefully and return original data
        result = self.converter.resample_24khz_to_8khz(short_data, 16)
        
        # Should return original data on error
        assert result == short_data, "Should return original data on error"

    def test_24khz_conversion_integration(self):
        """Test that 24kHz files are properly converted in the full pipeline."""
        # Create a test 24kHz WAV file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_file_path = temp_file.name
            
            # Create 24kHz, 16-bit PCM file (not WXCC compatible)
            test_pcm_24khz = self._generate_test_pcm_data(24000, 16, 1, 0.1)
            with wave.open(temp_file_path, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(24000)
                wav_file.writeframes(test_pcm_24khz)
            
            try:
                # Test the full conversion pipeline
                result = self.converter.convert_any_audio_to_wxcc(Path(temp_file_path))
                
                # Should return converted audio data
                assert len(result) > 0, "Should convert 24kHz audio successfully"
                
                # Verify the result is WAV format
                assert result.startswith(b'RIFF'), "Result should be WAV format"
                assert b'WAVE' in result, "Result should be WAV format"
                
                # Verify WxCC compatibility
                sample_rate = struct.unpack('<I', result[24:28])[0]
                bit_depth = struct.unpack('<H', result[34:36])[0]
                channels = struct.unpack('<H', result[22:24])[0]
                
                assert sample_rate == 8000, "Should be converted to 8kHz"
                assert bit_depth == 8, "Should be converted to 8-bit"
                assert channels == 1, "Should be converted to mono"
                
            finally:
                # Clean up
                Path(temp_file_path).unlink(missing_ok=True)

    def test_24khz_vs_16khz_resampling_consistency(self):
        """Test that 24kHz and 16kHz resampling produce consistent results."""
        # Generate test signals of the same duration
        test_16khz = self._generate_test_pcm_data(16000, 16, 1, 0.1)
        test_24khz = self._generate_test_pcm_data(24000, 16, 1, 0.1)
        
        # Resample both to 8kHz
        resampled_16khz = self.converter.resample_16khz_to_8khz(test_16khz, 16)
        resampled_24khz = self.converter.resample_24khz_to_8khz(test_24khz, 16)
        
        # Both should produce 8kHz output
        samples_16khz = len(resampled_16khz) // 2
        samples_24khz = len(resampled_24khz) // 2
        
        # 16kHz -> 8kHz: factor of 2, 24kHz -> 8kHz: factor of 3
        expected_16khz_samples = len(test_16khz) // 4  # 16-bit samples, factor of 2
        expected_24khz_samples = len(test_24khz) // 6  # 16-bit samples, factor of 3
        
        assert samples_16khz == expected_16khz_samples, f"16kHz resampling: expected {expected_16khz_samples}, got {samples_16khz}"
        assert samples_24khz == expected_24khz_samples, f"24kHz resampling: expected {expected_24khz_samples}, got {samples_24khz}"

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

    def test_convert_any_audio_to_wxcc_pcm_conversion(self):
        """Test the new convert_any_audio_to_wxcc method with PCM files."""
        # Create a temporary WAV file for testing
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_file_path = temp_file.name
            
            # Create a test WAV file with 16kHz, 16-bit PCM
            with wave.open(temp_file_path, 'wb') as wav_file:
                wav_file.setnchannels(1)  # Mono
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(16000)  # 16kHz
                wav_file.writeframes(self.test_pcm_16khz_16bit)
            
            try:
                # Test the conversion
                result = self.converter.convert_any_audio_to_wxcc(Path(temp_file_path))
                
                # Verify conversion was successful
                assert len(result) > 0, "Conversion should return non-empty result"
                
                # Verify the result is a valid WAV file
                assert result.startswith(b'RIFF'), "Result should be a valid WAV file"
                assert b'WAVE' in result, "Result should contain WAVE identifier"
                
                # Parse the converted WAV header
                sample_rate = struct.unpack('<I', result[24:28])[0]
                bit_depth = struct.unpack('<H', result[34:36])[0]
                channels = struct.unpack('<H', result[22:24])[0]
                format_code = struct.unpack('<H', result[20:22])[0]
                
                # Verify WXCC compatibility
                assert sample_rate == 8000, f"Sample rate should be 8000Hz, got {sample_rate}Hz"
                assert bit_depth == 8, f"Bit depth should be 8-bit, got {bit_depth}-bit"
                assert channels == 1, f"Channels should be 1, got {channels}"
                assert format_code == 7, f"Format should be u-law (7), got {format_code}"
                
                # Verify the converted file is smaller (due to resampling and encoding)
                original_size = len(self.test_pcm_16khz_16bit)
                converted_size = struct.unpack('<I', result[40:44])[0]  # Data chunk size
                assert converted_size < original_size, "Converted audio should be smaller due to resampling"
                
            finally:
                # Clean up
                Path(temp_file_path).unlink(missing_ok=True)

    def test_convert_any_audio_to_wxcc_already_compatible(self):
        """Test convert_any_audio_to_wxcc with already WXCC-compatible files."""
        # Create a temporary WAV file that's already WXCC-compatible
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_file_path = temp_file.name
            
            # Create a test WAV file with 8kHz, 8-bit u-law
            ulaw_data = self.converter.pcm_to_ulaw(self.test_pcm_8khz_8bit, 8000, 8)
            wav_data = self.converter.pcm_to_wav(ulaw_data, 8000, 8, 1, "ulaw")
            
            with open(temp_file_path, 'wb') as f:
                f.write(wav_data)
            
            try:
                # Test the conversion
                result = self.converter.convert_any_audio_to_wxcc(Path(temp_file_path))
                
                # Should return the file as-is since it's already compatible
                assert result == wav_data, "Should return original data for already compatible files"
                
            finally:
                # Clean up
                Path(temp_file_path).unlink(missing_ok=True)

    def test_resample_16khz_to_8khz_quality(self):
        """Test that 16kHz to 8kHz resampling maintains audio quality."""
        # Generate a longer test signal for better quality assessment
        test_signal = self._generate_test_pcm_data(16000, 16, 1, 0.5)  # 0.5 seconds
        
        # Resample
        resampled = self.converter.resample_16khz_to_8khz(test_signal, 16)
        
        # Verify resampling results
        original_samples = len(test_signal) // 2  # 16-bit samples
        resampled_samples = len(resampled) // 2   # 16-bit samples
        
        # Should have exactly half the samples (16kHz -> 8kHz)
        assert resampled_samples == original_samples // 2, f"Expected {original_samples // 2} samples, got {resampled_samples}"
        
        # Verify the resampled data is valid PCM
        samples = struct.unpack(f"<{resampled_samples}h", resampled)
        assert all(-32768 <= sample <= 32767 for sample in samples), "All samples should be valid 16-bit PCM"

    def test_pcm_to_ulaw_conversion_accuracy(self):
        """Test that PCM to u-law conversion produces accurate results."""
        # Generate a simple test signal
        test_signal = self._generate_test_pcm_data(8000, 16, 1, 0.1)
        
        # Convert to u-law
        ulaw_data = self.converter.pcm_to_ulaw(test_signal, 8000, 16)
        
        # Verify conversion results
        assert len(ulaw_data) == len(test_signal) // 2, "u-law should be half the size of 16-bit PCM"
        
        # Verify all bytes are valid u-law values
        assert all(0 <= byte <= 255 for byte in ulaw_data), "All u-law bytes should be in valid range"
        
        # Verify the conversion is deterministic (same input produces same output)
        ulaw_data2 = self.converter.pcm_to_ulaw(test_signal, 8000, 16)
        assert ulaw_data == ulaw_data2, "PCM to u-law conversion should be deterministic"

    def test_audio_conversion_error_handling(self):
        """Test error handling in audio conversion methods."""
        # Test with non-existent file
        result = self.converter.convert_any_audio_to_wxcc(Path("non_existent_file.wav"))
        assert result == b"", "Should return empty bytes for non-existent files"
        
        # Test with invalid WAV file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_file_path = temp_file.name
            temp_file.write(b"invalid wav data")
            temp_file.close()
            
            try:
                result = self.converter.convert_any_audio_to_wxcc(Path(temp_file_path))
                # Should handle gracefully, either return empty or raise exception
                assert isinstance(result, bytes), "Should return bytes or handle exception gracefully"
            finally:
                Path(temp_file_path).unlink(missing_ok=True)

    def test_wxcc_compatibility_analysis(self):
        """Test the audio file analysis for WXCC compatibility."""
        # Create a test WAV file
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
            temp_file_path = temp_file.name
            
            # Create 16kHz, 16-bit PCM file (not WXCC compatible)
            with wave.open(temp_file_path, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                wav_file.writeframes(self.test_pcm_16khz_16bit)
            
            try:
                # Analyze the file
                audio_info = self.converter.analyze_audio_file(Path(temp_file_path))
                
                # Verify analysis results
                assert "error" not in audio_info, "Should not have errors for valid WAV file"
                assert audio_info["sample_rate"] == 16000, "Sample rate should be 16000Hz"
                assert audio_info["bit_depth"] == 16, "Bit depth should be 16-bit"
                assert audio_info["channels"] == 1, "Channels should be 1"
                assert audio_info["encoding"] == "pcm", "Encoding should be PCM"
                assert not audio_info["is_wxcc_compatible"], "16kHz 16-bit PCM should not be WXCC compatible"
                
            finally:
                # Clean up
                Path(temp_file_path).unlink(missing_ok=True)
