"""
Audio utility functions for the Webex Contact Center BYOVA Gateway.

This module provides audio format conversion utilities that can be used
by all connectors to ensure WxCC compatibility.
"""

import logging
import os
import struct
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any


class AudioConverter:
    """
    Audio format converter utility class.

    Provides methods to convert between different audio formats and ensure
    WxCC compatibility (8kHz, 8-bit u-law, mono).
    """

    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize the audio converter.

        Args:
            logger: Optional logger instance. If not provided, creates a new one.
        """
        self.logger = logger or logging.getLogger(__name__)

    def analyze_audio_file(self, audio_path: Path) -> Dict[str, Any]:
        """
        Analyze audio file properties and return comprehensive metadata.

        Args:
            audio_path: Path to the audio file to analyze

        Returns:
            Dictionary containing audio file metadata
        """
        try:
            if not audio_path.exists():
                return {"error": f"File not found: {audio_path}"}

            # Get file size
            file_size = audio_path.stat().st_size

            # Read WAV file properties
            try:
                with wave.open(str(audio_path), "rb") as wav_file:
                    channels = wav_file.getnchannels()
                    sample_width = wav_file.getsampwidth()
                    sample_rate = wav_file.getframerate()
                    n_frames = wav_file.getnframes()
                    compression_type = wav_file.getcomptype()
                    bit_depth = sample_width * 8
                    duration = n_frames / sample_rate if sample_rate > 0 else 0

                    # Handle u-law encoding (format 7)
                    is_ulaw = compression_type == 7 or compression_type == b"ULAW"
                    is_pcm = compression_type == 1 or compression_type == b"NONE"
                    
                    # For u-law, bit depth is effectively 8-bit
                    effective_bit_depth = 8 if is_ulaw else bit_depth

                    return {
                        "file_path": str(audio_path),
                        "file_size": file_size,
                        "channels": channels,
                        "sample_width": sample_width,
                        "sample_rate": sample_rate,
                        "bit_depth": effective_bit_depth,
                        "n_frames": n_frames,
                        "duration": duration,
                        "compression_type": compression_type,
                        "encoding": "ulaw" if is_ulaw else "pcm",
                        "is_wxcc_compatible": (
                            sample_rate == 8000 and 
                            effective_bit_depth == 8 and 
                            channels == 1 and 
                            (is_ulaw or is_pcm)
                        )
                    }
            except Exception as wave_error:
                # If wave module fails, try to read the file manually to detect u-law
                self.logger.debug(f"Wave module failed: {wave_error}, trying manual detection")
                
                try:
                    with open(audio_path, 'rb') as f:
                        header = f.read(44)  # Read WAV header
                        
                        if len(header) >= 44 and header.startswith(b'RIFF') and b'WAVE' in header:
                            # Check for u-law format (format 7)
                            if len(header) >= 20:
                                format_code = int.from_bytes(header[20:22], byteorder='little')
                                if format_code == 7:
                                    return {
                                        "file_path": str(audio_path),
                                        "file_size": file_size,
                                        "channels": 1,  # Assume mono for u-law
                                        "sample_width": 1,
                                        "sample_rate": 8000,  # Assume 8kHz for u-law
                                        "bit_depth": 8,
                                        "n_frames": file_size - 44,  # Approximate
                                        "duration": (file_size - 44) / 8000,
                                        "compression_type": 7,
                                        "encoding": "ulaw",
                                        "is_wxcc_compatible": True
                                    }
                        
                        # If we get here, it's probably not a valid WAV file
                        return {
                            "error": "Not a valid WAV file or unsupported format",
                            "file_path": str(audio_path),
                            "file_size": file_size
                        }
                        
                except Exception as manual_error:
                    self.logger.debug(f"Manual detection also failed: {manual_error}")
                    return {
                        "error": f"Failed to analyze file: {manual_error}",
                        "file_path": str(audio_path),
                        "file_size": file_size
                    }

        except Exception as e:
            self.logger.error(f"Error analyzing audio file {audio_path}: {e}")
            return {"error": str(e)}

    def validate_wav_file(self, audio_path: Path) -> bool:
        """
        Validate if a file is a valid WAV file.

        Args:
            audio_path: Path to the file to validate

        Returns:
            True if the file is a valid WAV file, False otherwise
        """
        try:
            with wave.open(str(audio_path), "rb") as wav_file:
                # Just try to read basic properties to validate
                _ = wav_file.getnchannels()
                _ = wav_file.getsampwidth()
                _ = wav_file.getframerate()
                _ = wav_file.getnframes()
                return True

        except Exception:
            return False

    def resample_16khz_to_8khz(
        self, pcm_16khz_data: bytes, bit_depth: int = 16
    ) -> bytes:
        """
        Resample 16kHz PCM audio to 8kHz using simple decimation.

        AWS Lex returns 16kHz, 16-bit PCM, but WxCC expects 8kHz.
        This method downsamples by taking every other sample (simple decimation).

        Args:
            pcm_16khz_data: Raw PCM audio data at 16kHz
            bit_depth: Audio bit depth (default: 16)

        Returns:
            Resampled PCM audio data at 8kHz
        """
        try:
            if bit_depth == 16:
                # Convert bytes to 16-bit integers (little-endian)
                samples_16khz = struct.unpack(
                    f"<{len(pcm_16khz_data) // 2}h", pcm_16khz_data
                )

                # Simple decimation: take every other sample to go from 16kHz to 8kHz
                samples_8khz = samples_16khz[::2]

                # Convert back to bytes
                pcm_8khz_data = struct.pack(f"<{len(samples_8khz)}h", *samples_8khz)

                self.logger.info(
                    f"Resampled 16kHz to 8kHz: {len(pcm_16khz_data)} bytes -> {len(pcm_8khz_data)} bytes"
                )
                self.logger.info(
                    f"Sample count: {len(samples_16khz)} -> {len(samples_8khz)}"
                )

                return pcm_8khz_data

            elif bit_depth == 8:
                # For 8-bit audio, take every other byte
                samples_8khz = pcm_16khz_data[::2]
                self.logger.info(
                    f"Resampled 16kHz to 8kHz: {len(pcm_16khz_data)} bytes -> {len(samples_8khz)} bytes"
                )
                return samples_8khz

            else:
                self.logger.warning(
                    f"Unsupported bit depth for resampling: {bit_depth}, returning original data"
                )
                return pcm_16khz_data

        except Exception as e:
            self.logger.error(f"Error resampling 16kHz to 8kHz: {e}")
            # Return original data if resampling fails
            return pcm_16khz_data

    def pcm_to_ulaw(
        self, pcm_data: bytes, sample_rate: int = 8000, bit_depth: int = 16
    ) -> bytes:
        """
        Convert raw PCM audio data to u-law format for WxCC compatibility.

        WxCC expects 8-bit u-law encoding, but AWS Lex returns 16-bit PCM.
        This method converts the PCM data to u-law format.

        Args:
            pcm_data: Raw PCM audio data (typically 16-bit from Lex)
            sample_rate: Source sample rate (default: 8000)
            bit_depth: Source bit depth (default: 16)

        Returns:
            u-law encoded audio data as bytes
        """
        try:
            # Convert bytes to 16-bit integers (little-endian)
            if bit_depth == 16:
                # Convert 16-bit PCM to u-law
                pcm_samples = struct.unpack(f"<{len(pcm_data) // 2}h", pcm_data)
            elif bit_depth == 8:
                # Convert 8-bit PCM to u-law
                pcm_samples = struct.unpack(f"<{len(pcm_data)}B", pcm_data)
                # Convert 8-bit unsigned to 16-bit signed
                pcm_samples = [(sample - 128) * 256 for sample in pcm_samples]
            else:
                self.logger.warning(
                    f"Unsupported bit depth: {bit_depth}, returning original data"
                )
                return pcm_data

            # Convert to u-law
            ulaw_samples = []
            for sample in pcm_samples:
                ulaw_byte = self._linear_to_ulaw(sample)
                ulaw_samples.append(ulaw_byte)

            ulaw_data = bytes(ulaw_samples)
            self.logger.info(
                f"Converted {len(pcm_data)} bytes of {bit_depth}-bit PCM to u-law: {len(ulaw_data)} bytes"
            )
            return ulaw_data

        except Exception as e:
            self.logger.error(f"Error converting PCM to u-law: {e}")
            # Return original data if conversion fails
            return pcm_data

    def _linear_to_ulaw(self, sample: int) -> int:
        """
        Convert a linear PCM sample to u-law format.

        This is a simplified u-law encoding implementation.
        For production use, consider using a more sophisticated algorithm.

        Args:
            sample: Linear PCM sample (16-bit signed integer)

        Returns:
            u-law encoded byte
        """
        # Clamp sample to 16-bit range
        sample = max(-32768, min(32767, sample))

        # Handle sign
        sign = 0 if sample >= 0 else 0x80
        sample = abs(sample)

        # Find exponent (power of 2)
        if sample == 0:
            exponent = 0
        else:
            exponent = 0
            temp = sample
            while temp > 1:
                temp >>= 1
                exponent += 1

        # Calculate mantissa (4 bits)
        if exponent > 0:
            mantissa = (sample >> (exponent - 1)) & 0x0F
        else:
            mantissa = sample & 0x0F

        # Combine into u-law byte
        ulaw_byte = ~(sign | (exponent << 4) | mantissa)

        return ulaw_byte & 0xFF

    def convert_aws_lex_audio_to_wxcc(
        self, pcm_16khz_data: bytes, bit_depth: int = 16
    ) -> tuple[bytes, str]:
        """
        Complete conversion from AWS Lex audio format to WxCC-compatible format.

        This method performs the complete conversion:
        1. Resample 16kHz → 8kHz
        2. Convert 16-bit PCM → 8-bit u-law
        3. Package as WAV file (always required for WxCC)

        Args:
            pcm_16khz_data: Raw PCM audio data from AWS Lex (16kHz, 16-bit)
            bit_depth: Source bit depth (default: 16)

        Returns:
            Tuple of (wav_audio_data, "audio/wav")
        """
        try:
            # Step 1: Resample from 16kHz to 8kHz
            pcm_8khz = self.resample_16khz_to_8khz(pcm_16khz_data, bit_depth)

            # Step 2: Convert 8kHz PCM to u-law format
            ulaw_audio = self.pcm_to_ulaw(
                pcm_8khz, sample_rate=8000, bit_depth=bit_depth
            )

            # Step 3: Convert to WAV format (always required for WxCC)
            wav_audio = self.pcm_to_wav(
                ulaw_audio,
                sample_rate=8000,  # WxCC expects 8kHz
                bit_depth=8,  # WxCC expects 8-bit
                channels=1,  # WxCC expects mono
                encoding="ulaw",  # WxCC expects u-law
            )

            self.logger.info(
                "Converted 16kHz PCM to WxCC-compatible WAV format (8kHz, 8-bit u-law)"
            )
            return wav_audio, "audio/wav"

        except Exception as e:
            self.logger.error(f"Error in complete AWS Lex to WxCC conversion: {e}")
            # Return original data if conversion fails
            return pcm_16khz_data, "audio/pcm"

    def detect_audio_encoding(self, audio_bytes: bytes) -> str:
        """
        Detect the encoding of audio data based on byte patterns.
        
        Args:
            audio_bytes: Raw audio data bytes
            
        Returns:
            Detected encoding string ("ulaw", "pcm_16bit", "pcm_8bit", or "unknown")
        """
        if not audio_bytes or len(audio_bytes) < 10:
            return "unknown"
        
        try:
            # Check for u-law encoding patterns
            # u-law typically has values in the range 0x00-0xFF, with 0xFF often representing silence
            ulaw_indicators = 0
            pcm_indicators = 0
            
            # Sample some bytes to analyze patterns
            sample_size = min(100, len(audio_bytes))
            sample_bytes = audio_bytes[:sample_size]
            
            for byte in sample_bytes:
                # u-law characteristics: values are typically not evenly distributed
                # PCM characteristics: more even distribution, especially for speech
                if byte == 0xFF:  # Common u-law silence value
                    ulaw_indicators += 1
                elif byte == 0x00:  # Common u-law silence value
                    ulaw_indicators += 1
                elif 0x10 <= byte <= 0xF0:  # Common u-law speech range
                    ulaw_indicators += 1
                
                # PCM characteristics: more varied distribution
                if 0x01 <= byte <= 0xFE:
                    pcm_indicators += 1
            
            # Calculate confidence scores
            ulaw_confidence = ulaw_indicators / sample_size
            pcm_confidence = pcm_indicators / sample_size
            
            if self.logger and self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"Audio encoding detection - u-law confidence: {ulaw_confidence:.2f}, PCM confidence: {pcm_confidence:.2f}")
            
            # Determine encoding based on confidence scores
            if ulaw_confidence > 0.7:
                return "ulaw"
            elif pcm_confidence > 0.6:
                # Try to determine bit depth
                # For 16-bit PCM, we expect pairs of bytes
                if len(audio_bytes) % 2 == 0:
                    return "pcm_16bit"
                else:
                    return "pcm_8bit"
            else:
                return "unknown"
                
        except Exception as e:
            if self.logger:
                self.logger.error(f"Error detecting audio encoding: {e}")
            return "unknown"

    def pcm_to_wav(
        self,
        pcm_data: bytes,
        sample_rate: int = 8000,
        bit_depth: int = 8,
        channels: int = 1,
        encoding: str = "ulaw",
    ) -> bytes:
        """
        Convert PCM audio data to WAV format.

        Args:
            pcm_data: Raw PCM audio data
            sample_rate: Audio sample rate in Hz
            bit_depth: Audio bit depth
            channels: Number of audio channels
            encoding: Audio encoding format ("ulaw" or "pcm")

        Returns:
            WAV file data as bytes
        """
        try:
            # Calculate audio parameters
            bytes_per_sample = bit_depth // 8
            frame_size = channels * bytes_per_sample
            n_frames = len(pcm_data) // frame_size
            data_size = n_frames * frame_size
            file_size = 36 + data_size

            # Create WAV file header
            wav_header = bytearray()
            
            # RIFF header
            wav_header.extend(b'RIFF')
            wav_header.extend(struct.pack('<I', file_size))
            wav_header.extend(b'WAVE')
            
            # Format chunk
            wav_header.extend(b'fmt ')
            wav_header.extend(struct.pack('<I', 16))  # Format chunk size
            
            if encoding.lower() == "ulaw":
                wav_header.extend(struct.pack('<H', 7))  # Audio format: 7 = u-law
            else:
                wav_header.extend(struct.pack('<H', 1))  # Audio format: 1 = PCM
                
            wav_header.extend(struct.pack('<H', channels))  # Number of channels
            wav_header.extend(struct.pack('<I', sample_rate))  # Sample rate
            wav_header.extend(struct.pack('<I', sample_rate * frame_size))  # Byte rate
            wav_header.extend(struct.pack('<H', frame_size))  # Block align
            wav_header.extend(struct.pack('<H', bit_depth))  # Bits per sample
            
            # Data chunk header
            wav_header.extend(b'data')
            wav_header.extend(struct.pack('<I', data_size))
            
            # Combine header and audio data
            wav_data = wav_header + pcm_data
            
            self.logger.info(
                f"Created WAV file: {sample_rate}Hz, {bit_depth}bit, {channels} channel(s), "
                f"{encoding} encoding, {len(wav_data)} bytes total"
            )
            
            return bytes(wav_data)

        except Exception as e:
            self.logger.error(f"Error creating WAV file: {e}")
            # Return original PCM data if WAV creation fails
            return pcm_data

    def convert_any_audio_to_wxcc(self, audio_path: Path) -> bytes:
        """
        Convert any audio file to WXCC-compatible format.

        This method attempts to convert various audio formats to the
        WXCC-required format (8kHz, 8-bit u-law, mono).

        Args:
            audio_path: Path to the audio file to convert

        Returns:
            Audio data in WXCC-compatible WAV format
        """
        try:
            # First, analyze the audio file
            audio_info = self.analyze_audio_file(audio_path)
            
            if "error" in audio_info:
                self.logger.error(f"Cannot convert audio file: {audio_info['error']}")
                return b""
            
            # Check if already WXCC-compatible
            if audio_info.get("is_wxcc_compatible", False):
                self.logger.info(f"Audio file {audio_path} is already WXCC-compatible")
                # Read the file and return as-is
                with open(audio_path, 'rb') as f:
                    return f.read()
            
            # For now, return empty bytes for unsupported conversions
            # This can be enhanced later with proper format conversion libraries
            self.logger.warning(
                f"Audio conversion from {audio_info.get('encoding', 'unknown')} "
                f"to WXCC format not yet implemented for {audio_path}"
            )
            return b""
            
        except Exception as e:
            self.logger.error(f"Error converting audio file {audio_path}: {e}")
            return b""

    def analyze_audio_quality(self, audio_path: Path, logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
        """
        Analyze audio quality metrics for a given audio file.
        
        Args:
            audio_path: Path to the audio file to analyze
            logger: Optional logger instance
            
        Returns:
            Dictionary containing quality metrics and recommendations
        """
        try:
            # Get basic audio info
            audio_info = self.analyze_audio_file(audio_path)
            
            if "error" in audio_info:
                return {"error": audio_info["error"]}
            
            # Initialize quality metrics
            quality_metrics = {
                "file_path": str(audio_path),
                "overall_score": 0,
                "metrics": {},
                "recommendations": []
            }
            
            # Check sample rate compatibility
            sample_rate = audio_info.get("sample_rate", 0)
            if sample_rate == 8000:
                quality_metrics["metrics"]["sample_rate"] = {"score": 100, "status": "optimal"}
            elif sample_rate > 8000:
                quality_metrics["metrics"]["sample_rate"] = {"score": 70, "status": "acceptable"}
                quality_metrics["recommendations"].append("Consider downsampling to 8kHz for optimal WXCC compatibility")
            else:
                quality_metrics["metrics"]["sample_rate"] = {"score": 30, "status": "poor"}
                quality_metrics["recommendations"].append("Sample rate below 8kHz may cause audio quality issues")
            
            # Check bit depth compatibility
            bit_depth = audio_info.get("bit_depth", 0)
            if bit_depth == 8:
                quality_metrics["metrics"]["bit_depth"] = {"score": 100, "status": "optimal"}
            elif bit_depth == 16:
                quality_metrics["metrics"]["bit_depth"] = {"score": 80, "status": "good"}
                quality_metrics["recommendations"].append("Consider converting to 8-bit for optimal WXCC compatibility")
            else:
                quality_metrics["metrics"]["bit_depth"] = {"score": 40, "status": "poor"}
                quality_metrics["recommendations"].append("Unusual bit depth may cause compatibility issues")
            
            # Check channel configuration
            channels = audio_info.get("channels", 0)
            if channels == 1:
                quality_metrics["metrics"]["channels"] = {"score": 100, "status": "optimal"}
            else:
                quality_metrics["metrics"]["channels"] = {"score": 60, "status": "acceptable"}
                quality_metrics["recommendations"].append("Consider converting to mono for optimal WXCC compatibility")
            
            # Check encoding
            encoding = audio_info.get("encoding", "unknown")
            if encoding == "ulaw":
                quality_metrics["metrics"]["encoding"] = {"score": 100, "status": "optimal"}
            elif encoding == "pcm":
                quality_metrics["metrics"]["encoding"] = {"score": 80, "status": "good"}
                quality_metrics["recommendations"].append("Consider converting to u-law for optimal WXCC compatibility")
            else:
                quality_metrics["metrics"]["encoding"] = {"score": 30, "status": "poor"}
                quality_metrics["recommendations"].append("Unknown encoding format may cause compatibility issues")
            
            # Calculate overall score
            if quality_metrics["metrics"]:
                total_score = sum(metric["score"] for metric in quality_metrics["metrics"].values())
                quality_metrics["overall_score"] = total_score / len(quality_metrics["metrics"])
            
            # Add general recommendations based on overall score
            if quality_metrics["overall_score"] < 70:
                quality_metrics["recommendations"].append("Audio may have encoding or processing issues")
            
            return quality_metrics
            
        except Exception as e:
            if logger:
                logger.error(f"Error analyzing audio quality: {e}")
            return {"error": str(e)}


# Convenience functions for easy use
def resample_16khz_to_8khz(
    pcm_16khz_data: bytes, bit_depth: int = 16, logger: Optional[logging.Logger] = None
) -> bytes:
    """Convenience function to resample 16kHz PCM to 8kHz."""
    converter = AudioConverter(logger)
    return converter.resample_16khz_to_8khz(pcm_16khz_data, bit_depth)


def pcm_to_ulaw(
    pcm_data: bytes,
    sample_rate: int = 8000,
    bit_depth: int = 16,
    logger: Optional[logging.Logger] = None,
) -> bytes:
    """Convenience function to convert PCM to u-law."""
    converter = AudioConverter(logger)
    return converter.pcm_to_ulaw(pcm_data, sample_rate, bit_depth)


def pcm_to_wav(
    pcm_data: bytes,
    sample_rate: int = 8000,
    bit_depth: int = 8,
    channels: int = 1,
    encoding: str = "ulaw",
    logger: Optional[logging.Logger] = None,
) -> bytes:
    """Convenience function to convert PCM to WAV."""
    converter = AudioConverter(logger)
    return converter.pcm_to_wav(pcm_data, sample_rate, bit_depth, channels, encoding)


def convert_aws_lex_audio_to_wxcc(
    pcm_16khz_data: bytes, bit_depth: int = 16, logger: Optional[logging.Logger] = None
) -> tuple[bytes, str]:
    """Convenience function for complete AWS Lex to WxCC conversion."""
    converter = AudioConverter(logger)
    return converter.convert_aws_lex_audio_to_wxcc(pcm_16khz_data, bit_depth)


def get_audio_file_info(
    audio_path: Path, logger: Optional[logging.Logger] = None
) -> Dict[str, Any]:
    """
    Get comprehensive audio file information.
    
    Args:
        audio_path: Path to the audio file to analyze
        logger: Optional logger instance
        
    Returns:
        Dictionary containing audio file metadata
    """
    converter = AudioConverter(logger)
    return converter.analyze_audio_file(audio_path)


def is_wxcc_compatible(
    audio_path: Path, logger: Optional[logging.Logger] = None
) -> bool:
    """
    Check if audio file is already in WXCC-compatible format.
    
    Args:
        audio_path: Path to the audio file to check
        logger: Optional logger instance
        
    Returns:
        True if the file is WXCC-compatible, False otherwise
    """
    converter = AudioConverter(logger)
    audio_info = converter.analyze_audio_file(audio_path)
    return audio_info.get("is_wxcc_compatible", False) if "error" not in audio_info else False


def convert_any_audio_to_wxcc(
    audio_path: Path, logger: Optional[logging.Logger] = None
) -> bytes:
    """
    Convert any audio file to WXCC-compatible format.
    
    Args:
        audio_path: Path to the audio file to convert
        logger: Optional logger instance
        
    Returns:
        Audio data in WXCC-compatible WAV format
    """
    converter = AudioConverter(logger)
    return converter.convert_any_audio_to_wxcc(audio_path)


def validate_wav_file(
    audio_path: Path, logger: Optional[logging.Logger] = None
) -> bool:
    """
    Validate if a file is a valid WAV file.
    
    Args:
        audio_path: Path to the file to validate
        logger: Optional logger instance
        
    Returns:
        True if the file is a valid WAV file, False otherwise
    """
    converter = AudioConverter(logger)
    return converter.validate_wav_file(audio_path)
