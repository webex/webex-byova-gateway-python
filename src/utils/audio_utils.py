"""
Audio utility functions for the Webex Contact Center BYOVA Gateway.

This module provides audio format conversion utilities that can be used
by all connectors to ensure WxCC compatibility. It also includes functionality
for recording audio to WAV files with silence detection.
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
                                if format_code == 7:  # u-law
                                    # Extract other properties from header
                                    channels = int.from_bytes(header[22:24], byteorder='little')
                                    sample_rate = int.from_bytes(header[24:28], byteorder='little')
                                    bit_depth = 8  # u-law is effectively 8-bit
                                    
                                    # Estimate duration from file size
                                    estimated_duration = (file_size - 44) / (sample_rate * channels)
                                    
                                    return {
                                        "file_path": str(audio_path),
                                        "file_size": file_size,
                                        "channels": channels,
                                        "sample_rate": sample_rate,
                                        "bit_depth": bit_depth,
                                        "n_frames": int(estimated_duration * sample_rate),
                                        "duration": estimated_duration,
                                        "compression_type": 7,
                                        "encoding": "ulaw",
                                        "is_wxcc_compatible": (
                                            sample_rate == 8000 and 
                                            bit_depth == 8 and 
                                            channels == 1
                                        )
                                    }
                except Exception as manual_error:
                    self.logger.debug(f"Manual detection also failed: {manual_error}")
                
                # If all else fails, return error
                raise wave_error

        except Exception as e:
            self.logger.error(f"Error analyzing audio file {audio_path}: {e}")
            return {"error": str(e)}

    def resample_24khz_to_8khz(self, pcm_24khz_data: bytes, bit_depth: int = 16) -> bytes:
        """
        Resample 24kHz PCM audio to 8kHz using simple decimation.

        Args:
            pcm_24khz_data: Raw PCM audio data at 24kHz
            bit_depth: Audio bit depth (default: 16)

        Returns:
            Resampled PCM audio data at 8kHz
        """
        try:
            if bit_depth == 16:
                # Convert bytes to 16-bit integers (little-endian)
                samples_24khz = struct.unpack(
                    f"<{len(pcm_24khz_data) // 2}h", pcm_24khz_data
                )

                # Simple decimation: take every 3rd sample to go from 24kHz to 8kHz
                samples_8khz = samples_24khz[::3]

                # Convert back to bytes
                pcm_8khz_data = struct.pack(f"<{len(samples_8khz)}h", *samples_8khz)

                self.logger.info(
                    f"Resampled 24kHz to 8kHz: {len(pcm_24khz_data)} bytes -> {len(pcm_8khz_data)} bytes"
                )
                self.logger.info(
                    f"Sample count: {len(samples_24khz)} -> {len(samples_8khz)}"
                )

                return pcm_8khz_data

            elif bit_depth == 8:
                # For 8-bit audio, take every 3rd byte
                samples_8khz = pcm_24khz_data[::3]
                self.logger.info(
                    f"Resampled 24kHz to 8kHz: {len(pcm_24khz_data)} bytes -> {len(samples_8khz)} bytes"
                )
                return samples_8khz

            else:
                self.logger.warning(
                    f"Unsupported bit depth for 24kHz resampling: {bit_depth}, returning original data"
                )
                return pcm_24khz_data

        except Exception as e:
            self.logger.error(f"Error resampling 24kHz to 8kHz: {e}")
            # Return original data if resampling fails
            return pcm_24khz_data

    def convert_any_audio_to_wxcc(self, audio_path: Path) -> bytes:
        """
        Convert any audio file to WXCC-compatible format (8kHz, 8-bit u-law, mono).

        This method handles various input formats and converts them to the format
        expected by Webex Contact Center.

        Args:
            audio_path: Path to the audio file to convert

        Returns:
            Audio data in WXCC-compatible WAV format (8kHz, 8-bit u-law)
        """
        try:
            # Analyze the audio file first
            audio_info = self.analyze_audio_file(audio_path)
            
            if "error" in audio_info and audio_info["error"] is not None:
                self.logger.error(f"Cannot convert audio file: {audio_info['error']}")
                return b""

            # Check if already in correct format
            if audio_info.get("is_wxcc_compatible", False):
                self.logger.info(f"Audio file {audio_path} already in WXCC-compatible format")
                # Return the entire file as-is (including WAV headers)
                with open(audio_path, 'rb') as f:
                    return f.read()

            self.logger.info(f"Converting audio file {audio_path} to WXCC-compatible format")
            self.logger.info(
                f"Original format: {audio_info['sample_rate']}Hz, {audio_info['bit_depth']}bit, "
                f"{audio_info['channels']} channel(s), compression: {audio_info['compression_type']}"
            )

            # Read the original audio data
            if audio_info.get("encoding") == "ulaw":
                # For u-law files, read raw data manually
                with open(audio_path, 'rb') as f:
                    # Skip WAV header (44 bytes) and read audio data
                    f.seek(44)
                    pcm_data = f.read()
            else:
                # For PCM files, use wave module
                with wave.open(str(audio_path), "rb") as wav_file:
                    pcm_data = wav_file.readframes(wav_file.getnframes())

            # Step 1: Resample if needed
            if audio_info["sample_rate"] != 8000:
                if audio_info["sample_rate"] == 16000:
                    pcm_data = self.resample_16khz_to_8khz(pcm_data, audio_info["bit_depth"])
                    self.logger.info(f"Resampled from {audio_info['sample_rate']}Hz to 8kHz")
                elif audio_info["sample_rate"] == 24000:
                    pcm_data = self.resample_24khz_to_8khz(pcm_data, audio_info["bit_depth"])
                    self.logger.info(f"Resampled from {audio_info['sample_rate']}Hz to 8kHz")
                else:
                    self.logger.warning(
                        f"Unsupported sample rate: {audio_info['sample_rate']}Hz, using original"
                    )

            # Step 2: Convert to u-law if needed
            if audio_info["bit_depth"] != 8 or audio_info["compression_type"] != b"NONE":
                pcm_data = self.pcm_to_ulaw(pcm_data, sample_rate=8000, bit_depth=16)
                self.logger.info("Converted PCM to u-law format")

            # Step 3: Convert to WAV format with proper headers
            wav_data = self.pcm_to_wav(
                pcm_data,
                sample_rate=8000,  # WXCC expects 8kHz
                bit_depth=8,  # WXCC expects 8-bit
                channels=1,  # WXCC expects mono
                encoding="ulaw",  # WXCC expects u-law
            )

            self.logger.info(
                f"Successfully converted to WXCC-compatible format: {len(wav_data)} bytes"
            )
            return wav_data

        except Exception as e:
            self.logger.error(f"Error converting audio file {audio_path}: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            # Return empty bytes if conversion fails
            return b""

    def validate_wav_file(self, audio_path: Path) -> bool:
        """
        Validate if a file is a valid WAV file.

        Args:
            audio_path: Path to the file to validate

        Returns:
            True if the file is a valid WAV file, False otherwise
        """
        try:
            if not audio_path.exists():
                return False

            with wave.open(str(audio_path), "rb") as wav_file:
                # Try to read basic properties - this will fail if not a valid WAV
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
                # Clamp sample to 16-bit range
                sample = max(-32768, min(32767, int(sample)))

                # Convert to u-law
                ulaw_byte = self._linear_to_ulaw(sample)
                ulaw_samples.append(ulaw_byte)

            ulaw_data = bytes(ulaw_samples)
            self.logger.info(
                f"Converted {len(pcm_data)} bytes PCM ({bit_depth}bit) to {len(ulaw_data)} bytes u-law"
            )

            return ulaw_data

        except Exception as e:
            self.logger.error(f"Error converting PCM to u-law: {e}")
            # Return original PCM data if conversion fails
            return pcm_data

    def pcm_to_wav(
        self,
        pcm_data: bytes,
        sample_rate: int = 8000,
        bit_depth: int = 8,
        channels: int = 1,
        encoding: str = "ulaw",
    ) -> bytes:
        """
        Convert raw PCM audio data to WAV format compatible with WxCC.

        WxCC expects: 8kHz, 8-bit u-law, mono audio
        Avoid: 16kHz, 16-bit PCM (causes 5-second delay and missed caller responses)

        Args:
            pcm_data: Raw PCM audio data from AWS Lex
            sample_rate: Audio sample rate in Hz (default: 8000 for WxCC compatibility)
            bit_depth: Audio bit depth (default: 8 for WxCC compatibility)
            channels: Number of audio channels (default: 1 for mono)
            encoding: Audio encoding (default: "ulaw" for WxCC compatibility)

        Returns:
            WAV format audio data as bytes
        """
        try:
            # WAV file header constants
            RIFF_HEADER = b"RIFF"
            WAVE_FORMAT = b"WAVE"
            FMT_CHUNK = b"fmt "
            DATA_CHUNK = b"data"

            # WxCC-compatible audio format settings
            if encoding == "ulaw":
                # u-law encoding (WxCC preferred)
                audio_format = 7  # WAVE_FORMAT_MULAW
                bytes_per_sample = 1  # 8-bit u-law = 1 byte per sample
            else:
                # PCM encoding (fallback)
                audio_format = 1  # WAVE_FORMAT_PCM
                bytes_per_sample = bit_depth // 8

            # Calculate sizes
            block_align = channels * bytes_per_sample
            byte_rate = sample_rate * block_align
            data_size = len(pcm_data)
            file_size = 36 + data_size  # 36 bytes for headers + data size

            # Build WAV header with WxCC-compatible format
            wav_header = struct.pack(
                "<4sI4s4sIHHIIHH4sI",
                RIFF_HEADER,  # RIFF identifier
                file_size,  # File size - 8
                WAVE_FORMAT,  # WAVE format
                FMT_CHUNK,  # Format chunk identifier
                16,  # Format chunk size
                audio_format,  # Audio format (7 = u-law, 1 = PCM)
                channels,  # Number of channels (1 = mono)
                sample_rate,  # Sample rate (8000 Hz for WxCC)
                byte_rate,  # Byte rate
                block_align,  # Block align
                bit_depth,  # Bits per sample (8 for u-law)
                DATA_CHUNK,  # Data chunk identifier
                data_size,  # Data size
            )

            # Combine header and audio data
            wav_data = wav_header + pcm_data

            self.logger.info(
                f"Converted PCM to WAV: {len(pcm_data)} bytes PCM -> {len(wav_data)} bytes WAV"
            )
            self.logger.info(
                f"WAV format: {sample_rate}Hz, {bit_depth}bit, {channels} channel(s), encoding: {encoding}"
            )
            self.logger.info(
                f"WxCC compatibility: {'YES' if sample_rate == 8000 and bit_depth == 8 and encoding == 'ulaw' else 'NO'}"
            )

            return wav_data

        except Exception as e:
            self.logger.error(f"Error converting PCM to WAV: {e}")
            # Return original PCM data if conversion fails
            return pcm_data

    def _linear_to_ulaw(self, sample: int) -> int:
        """
        Convert a 16-bit linear PCM sample to 8-bit u-law.

        Args:
            sample: 16-bit signed PCM sample (-32768 to 32767)

        Returns:
            8-bit u-law sample (0 to 255)
        """
        # u-law encoding table (simplified implementation)
        MULAW_BIAS = 0x84
        MULAW_CLIP = 32635

        # Clamp the sample
        if sample > MULAW_CLIP:
            sample = MULAW_CLIP
        elif sample < -MULAW_CLIP:
            sample = -MULAW_CLIP

        # Add bias
        sample += MULAW_BIAS

        # Get sign bit
        sign = (sample >> 8) & 0x80
        if sign != 0:
            sample = -sample
        if sample > MULAW_CLIP:
            sample = MULAW_CLIP

        # Find exponent
        exponent = 7
        mask = 0x4000
        while (sample & mask) == 0 and exponent > 0:
            mask >>= 1
            exponent -= 1

        # Calculate mantissa
        mantissa = (sample >> (exponent + 3)) & 0x0F

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
                if len(audio_bytes) % 2 == 0:
                    return "pcm_16bit"
                else:
                    return "pcm_8bit"
            else:
                # Default to u-law for telephony systems
                return "ulaw"
                
        except Exception as e:
            if self.logger:
                self.logger.debug(f"Error detecting audio encoding: {e}")
            # Default to u-law for telephony systems
            return "ulaw"


class AudioRecorder:
    """
    Audio recorder utility class for recording caller audio to WAV files.

    Features:
    - Records audio data to WAV files
    - Implements silence detection
    - Automatically finalizes recording after a configured silence threshold
    - Supports various audio formats and sample rates
    """

    def __init__(
        self,
        conversation_id: str,
        output_dir: str = "logs",
        silence_threshold: int = 3000,
        silence_duration: float = 2.0,
        quiet_threshold: int = 20,
        sample_rate: int = 8000,
        bit_depth: int = 8,
        channels: int = 1,
        encoding: str = "ulaw",
        buffer_only: bool = False,
        on_audio_ready: Optional[callable] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """
        Initialize the audio recorder.

        Args:
            conversation_id: Unique identifier for the conversation
            output_dir: Directory to save WAV files (default: 'logs')
            silence_threshold: Amplitude threshold for silence detection
            silence_duration: Amount of silence (in seconds) before finalizing the recording
            quiet_threshold: How far from 127 (quiet background) to consider "silence" (default: 20)
            sample_rate: Audio sample rate in Hz
            bit_depth: Audio bit depth
            channels: Number of audio channels
            encoding: Audio encoding format
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
        self.conversation_id = conversation_id
        self.output_dir = Path(output_dir)
        self.silence_threshold = silence_threshold
        self.silence_duration = silence_duration
        self.quiet_threshold = quiet_threshold
        self.sample_rate = sample_rate
        self.bit_depth = bit_depth
        self.channels = channels
        self.encoding = encoding

        # Internal state
        self.buffer_only = buffer_only
        self.on_audio_ready = on_audio_ready
        self.audio_buffer = bytearray()
        self.wav_file = None
        self.recording = False
        self.last_audio_time = 0
        self.file_path = None
        self.waiting_for_speech = True  # Wait for first non-silence before starting recording
        self.speech_detected = False    # Track if we've ever detected speech

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            f"AudioRecorder initialized for conversation {conversation_id} "
            f"(silence threshold: {silence_threshold}, duration: {silence_duration}s, "
            f"quiet threshold: {quiet_threshold}, waiting for speech: {self.waiting_for_speech})"
        )

    def _create_ulaw_wav_file(self, file_path: str) -> None:
        """
        Create a u-law WAV file with proper headers.
        
        Args:
            file_path: Path to the WAV file to create
        """
        try:
            # Create the file and write u-law WAV header
            # Note: Don't use 'with' statement as we need to keep the file open
            f = open(file_path, 'wb')
            
            # WAV file header for u-law encoding
            # RIFF header
            f.write(b'RIFF')
            f.write(struct.pack('<I', 0))  # File size placeholder
            f.write(b'WAVE')
            
            # Format chunk
            f.write(b'fmt ')
            f.write(struct.pack('<I', 16))  # Format chunk size
            f.write(struct.pack('<H', 7))   # Audio format: 7 = u-law
            f.write(struct.pack('<H', self.channels))  # Number of channels
            f.write(struct.pack('<I', self.sample_rate))  # Sample rate
            f.write(struct.pack('<I', self.sample_rate * self.channels))  # Byte rate
            f.write(struct.pack('<H', self.channels))  # Block align
            f.write(struct.pack('<H', 8))  # Bits per sample (u-law is effectively 8-bit)
            
            # Data chunk header
            f.write(b'data')
            f.write(struct.pack('<I', 0))  # Data size placeholder
            
            # Store file handle and position for later writing
            self._wav_file_handle = f
            self._data_start_pos = f.tell()
            self._riff_size_pos = 4
            
        except Exception as e:
            self.logger.error(f"Error creating u-law WAV file: {e}")
            # Clean up file handle if creation failed
            if hasattr(self, '_wav_file_handle') and self._wav_file_handle:
                try:
                    self._wav_file_handle.close()
                except:
                    pass
                self._wav_file_handle = None
            raise

    def _write_ulaw_audio_data(self, audio_data: bytes) -> None:
        """
        Write u-law audio data to the WAV file.
        
        Args:
            audio_data: u-law encoded audio data
        """
        try:
            if hasattr(self, '_wav_file_handle') and self._wav_file_handle:
                # Write audio data
                self._wav_file_handle.write(audio_data)
                
                # Update file size in RIFF header
                current_pos = self._wav_file_handle.tell()
                file_size = current_pos - 8
                data_size = current_pos - self._data_start_pos
                
                self.logger.debug(f"Writing {len(audio_data)} bytes, updating headers: file_size={file_size}, data_size={data_size}")
                
                # Seek back to update headers
                self._wav_file_handle.seek(self._riff_size_pos)
                self._wav_file_handle.write(struct.pack('<I', file_size))
                
                self._wav_file_handle.seek(self._data_start_pos - 4)
                self._wav_file_handle.write(struct.pack('<I', data_size))
                
                # Return to end of file
                self._wav_file_handle.seek(current_pos)
                
                # Flush to ensure data is written to disk
                self._wav_file_handle.flush()
                
            else:
                self.logger.error("No u-law WAV file handle available for writing")
                
        except Exception as e:
            self.logger.error(f"Error writing u-law audio data: {e}")
            raise

    def _close_ulaw_wav_file(self) -> None:
        """Close the u-law WAV file properly."""
        try:
            if hasattr(self, '_wav_file_handle') and self._wav_file_handle:
                self._wav_file_handle.close()
                self._wav_file_handle = None
        except Exception as e:
            self.logger.error(f"Error closing u-law WAV file: {e}")

    def start_recording(self) -> None:
        """
        Start a new audio recording session.

        If a recording is already in progress, it will be finalized first.
        """
        if self.recording:
            self.logger.info(
                f"Finalizing previous recording before starting a new one for {self.conversation_id}"
            )
            self.finalize_recording()

        # Generate filename with timestamp and conversation ID (only if not buffer-only)
        if not self.buffer_only:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"caller_audio_{self.conversation_id}_{timestamp}.wav"
            self.file_path = self.output_dir / filename

            # Set up WAV file based on encoding type
            if self.encoding.lower() == "ulaw":
                # Use custom u-law WAV file creation
                self._create_ulaw_wav_file(str(self.file_path))
                self.wav_file = None  # We're using custom file handling
            else:
                # Use standard wave module for PCM
                self.wav_file = wave.open(str(self.file_path), "wb")
                self.wav_file.setnchannels(self.channels)
                self.wav_file.setsampwidth(self.bit_depth // 8)
                self.wav_file.setframerate(self.sample_rate)
        else:
            # Buffer-only mode: no file creation
            self.file_path = None

        # Reset state
        self.audio_buffer = bytearray()
        self.recording = True
        self.last_audio_time = time.time()

        if self.buffer_only:
            self.logger.info(
                f"Started buffering audio for conversation {self.conversation_id} (buffer-only mode)"
            )
        else:
            self.logger.info(
                f"Started recording audio for conversation {self.conversation_id} to {self.file_path}"
            )

    def add_audio_data(self, audio_data: bytes, encoding: str = "ulaw") -> bool:
        """
        Add audio data to the current recording.

        Args:
            audio_data: Audio data bytes to add to the recording
            encoding: Format of the input audio data (default: 'ulaw')

        Returns:
            True if recording continues, False if recording was finalized due to silence
        """
        if not audio_data:
            self.logger.warning(
                f"Received empty audio data for conversation {self.conversation_id}"
            )
            return True

        # Log audio data characteristics
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                f"Adding {len(audio_data)} bytes of {encoding} audio data to recording"
            )
            self.logger.debug(f"First 10 bytes: {audio_data[:10]}")
            # Log hex representation for debugging
            hex_preview = audio_data[:20].hex()
            self.logger.debug(f"Audio data hex preview: {hex_preview}...")

        # Convert audio data to the recording format if needed
        processed_audio = self._convert_audio_to_recording_format(audio_data, encoding)
        
        # Add audio data to buffer
        self.audio_buffer.extend(processed_audio)
        self.logger.debug(
            f"Buffer size after adding data: {len(self.audio_buffer)} bytes"
        )
        
        # Check if we have enough data to process
        # Use frame-aligned buffer sizes based on encoding and bit depth
        frame_size = self._get_frame_size()
        if len(self.audio_buffer) >= frame_size:
            # Write to WAV file - ensure we have a copy of the buffer before clearing
            buffer_copy = bytes(self.audio_buffer)
            
            # Check for silence first to determine if we should start recording
            is_silence = self.detect_silence(buffer_copy)
            
            if self.waiting_for_speech:
                if is_silence:
                    # Still waiting for speech, don't start recording yet
                    self.logger.debug(
                        f"Still waiting for speech in conversation {self.conversation_id}, "
                        f"silence detected in audio segment"
                    )
                    # Clear the buffer since we're not recording yet
                    self.audio_buffer = bytearray()
                    return True
                else:
                    # Speech detected! Start recording now
                    self.waiting_for_speech = False
                    self.speech_detected = True
                    self.last_audio_time = time.time()
                    self.start_recording()
                    self.logger.info(
                        f"Speech detected! Starting recording for conversation {self.conversation_id}"
                    )
            
            # At this point, we're either already recording or just started
            if self.recording:
                if not self.buffer_only:
                    # File recording mode: write to WAV file
                    try:
                        if self.encoding.lower() == "ulaw" and hasattr(self, '_wav_file_handle'):
                            # Use custom u-law writing
                            self._write_ulaw_audio_data(buffer_copy)
                            bytes_written = len(buffer_copy)
                            self.logger.debug(
                                f"Wrote {bytes_written} bytes to u-law WAV file {self.file_path}"
                            )
                        elif self.wav_file:
                            # Use standard wave module
                            bytes_written = len(buffer_copy)
                            self.wav_file.writeframes(buffer_copy)
                            self.logger.debug(
                                f"Wrote {bytes_written} bytes to WAV file {self.file_path}"
                            )
                        else:
                            self.logger.error("No WAV file handle available for writing")
                            
                    except Exception as e:
                        self.logger.error(f"Error writing to WAV file: {e}")
                else:
                    # Buffer-only mode: just log the data addition
                    self.logger.debug(
                        f"Added {len(buffer_copy)} bytes to buffer (buffer-only mode)"
                    )

                # Check for silence after recording has started
                if is_silence:
                    # Check if silence duration threshold exceeded
                    silence_time = time.time() - self.last_audio_time
                    self.logger.debug(
                        f"Silence detected in audio segment, silence duration so far: {silence_time:.2f}s "
                        f"(threshold: {self.silence_duration}s)"
                    )
                    if silence_time >= self.silence_duration:
                        self.logger.info(
                            f"Silence detected for {silence_time:.2f}s in conversation {self.conversation_id}, finalizing recording"
                        )
                        
                        # Get the audio data before finalizing (make a copy)
                        audio_data = bytes(self.audio_buffer) if self.audio_buffer else None
                        
                        # Clear the buffer before finalizing (to prevent double-clearing)
                        self.audio_buffer = bytearray()
                        
                        # Finalize the recording
                        self.finalize_recording()
                        
                        # Invoke callback if provided
                        if self.on_audio_ready and audio_data:
                            try:
                                self.on_audio_ready(self.conversation_id, audio_data)
                            except Exception as e:
                                self.logger.error(f"Error in on_audio_ready callback: {e}")
                        
                        return False
                else:
                    # Reset the last audio time as we detected non-silence
                    self.logger.debug(
                        f"Non-silence detected in audio segment, resetting silence timer for {self.conversation_id}"
                    )
                    self.last_audio_time = time.time()

            # Clear the buffer after processing
            self.audio_buffer = bytearray()

        return True

    def check_silence_timeout(self) -> bool:
        """
        Check if the recording should be finalized due to silence timeout.
        This method can be called periodically to check for silence even when no audio data is received.
        
        Returns:
            True if recording continues, False if recording was finalized due to silence
        """
        if not self.recording:
            # If we're not recording yet, check if we should start recording
            if self.waiting_for_speech:
                self.logger.debug(
                    f"Still waiting for speech in conversation {self.conversation_id}, "
                    f"no recording started yet"
                )
                return True
            return True
            
        # Check if we've exceeded the silence duration
        current_time = time.time()
        silence_time = current_time - self.last_audio_time
        
        if silence_time >= self.silence_duration:
            self.logger.info(
                f"Silence timeout reached ({silence_time:.2f}s) for conversation {self.conversation_id}, finalizing recording"
            )
            
            # Get the audio data before finalizing (make a copy)
            audio_data = bytes(self.audio_buffer) if self.audio_buffer else None
            
            # Finalize the recording
            self.finalize_recording()
            
            # Invoke callback if provided
            if self.on_audio_ready and audio_data:
                try:
                    self.on_audio_ready(self.conversation_id, audio_data)
                except Exception as e:
                    self.logger.error(f"Error in on_audio_ready callback: {e}")
            
            return False
            
        return True

    def _get_frame_size(self) -> int:
        """
        Get the appropriate frame size for buffering based on audio format.
        
        Returns:
            Frame size in bytes for optimal buffering
        """
        # For 8kHz audio, use 160 samples per frame (20ms chunks)
        # This provides good balance between latency and efficiency
        samples_per_frame = 160
        
        if self.encoding == "ulaw":
            # u-law is 8-bit, so 1 byte per sample
            return samples_per_frame
        elif self.encoding == "pcm":
            # PCM bit depth determines bytes per sample
            bytes_per_sample = self.bit_depth // 8
            return samples_per_frame * bytes_per_sample
        else:
            # Default to 640 bytes for unknown formats
            return 640

    def _convert_audio_to_recording_format(self, audio_data: bytes, input_encoding: str) -> bytes:
        """
        Convert incoming audio data to the recording format.
        
        Args:
            audio_data: Raw audio data bytes
            input_encoding: Encoding of the input audio data
            
        Returns:
            Audio data converted to the recording format
        """
        try:
            # If input encoding matches recording encoding, return as-is
            if input_encoding.lower() == self.encoding.lower():
                self.logger.debug(f"Audio format matches recording format ({input_encoding})")
                return audio_data
            
            # Convert between different formats
            if input_encoding.lower() == "pcm" and self.encoding.lower() == "ulaw":
                # Convert PCM to u-law
                self.logger.debug("Converting PCM to u-law for recording")
                # Assume 16-bit PCM if we can't determine bit depth
                assumed_bit_depth = 16
                if len(audio_data) % 2 == 0:  # Even number of bytes suggests 16-bit
                    assumed_bit_depth = 16
                else:
                    assumed_bit_depth = 8
                
                # Use the AudioConverter to convert PCM to u-law
                converter = AudioConverter(self.logger)
                return converter.pcm_to_ulaw(audio_data, sample_rate=self.sample_rate, bit_depth=assumed_bit_depth)
            
            elif input_encoding.lower() == "ulaw" and self.encoding.lower() == "pcm":
                # Convert u-law to PCM
                self.logger.debug("Converting u-law to PCM for recording")
                # This is more complex and might not be needed
                # For now, return as-is and log a warning
                self.logger.warning("u-law to PCM conversion not implemented, using original data")
                return audio_data
            
            else:
                # Unknown conversion, log warning and return as-is
                self.logger.warning(
                    f"Unknown audio format conversion: {input_encoding} -> {self.encoding}, using original data"
                )
                return audio_data
                
        except Exception as e:
            self.logger.error(f"Error converting audio format: {e}")
            # Return original data if conversion fails
            return audio_data

    def detect_silence(self, audio_data: bytes) -> bool:
        """
        Detect if audio data contains only silence.

        Args:
            audio_data: Audio data bytes to analyze

        Returns:
            True if the audio is below the silence threshold
        """
        if not audio_data or len(audio_data) == 0:
            self.logger.debug("Empty audio data passed to silence detection")
            return True
        # For u-law encoding, we can directly check byte values
        # Silence in u-law is typically represented by values close to 0xFF
        if self.encoding == "ulaw":
            # Use the configured silence threshold to determine sensitivity
            # The threshold represents the percentage of non-silent samples allowed
            # Higher threshold = more sensitive (more likely to detect silence)
            threshold_percentage = min(100, max(1, 100 - (self.silence_threshold / 100)))
            
            # Enhanced silence detection: consider both true silence (0xFF) and quiet background noise
            # In u-law, 127 represents very quiet background noise (room tone, breathing, etc.)
            # Values closer to 127 are quieter, values closer to 0 or 255 are louder
            
            # Count bytes that represent significant audio (not silence or quiet background)
            # We'll consider values in the "quiet" range (around 127) as effective silence
            quiet_threshold = self.quiet_threshold  # Use the quiet_threshold from __init__
            significant_audio_count = sum(
                1 for byte in audio_data 
                if abs(byte - 127) > quiet_threshold and byte != 0xFF
            )
            
            # Calculate percentage of significant audio samples
            if len(audio_data) > 0:
                significant_audio_percentage = (significant_audio_count / len(audio_data)) * 100
                self.logger.debug(
                    f"Detected {significant_audio_percentage:.2f}% significant audio samples "
                    f"(threshold: {threshold_percentage:.1f}%, configured: {self.silence_threshold})"
                )

                # If less than threshold percentage of samples are significant audio, consider it silence
                is_silence = significant_audio_percentage < threshold_percentage
                if is_silence:
                    self.logger.debug("Audio segment detected as silence (including quiet background)")
                else:
                    self.logger.debug("Audio segment contains significant speech/audio")

                return is_silence

        # For PCM data, analyze amplitude
        # TODO: Implement proper PCM silence detection if needed
        return False

    def finalize_recording(self) -> Optional[str]:
        """
        Finalize the current recording and close the WAV file.

        Returns:
            The path to the saved WAV file, or None if no recording was in progress
        """
        if not self.recording:
            if self.waiting_for_speech:
                self.logger.info(
                    f"No recording to finalize for conversation {self.conversation_id} - "
                    f"still waiting for speech"
                )
            return None

        # Write any remaining data (only if not buffer-only)
        if self.audio_buffer and not self.buffer_only:
            buffer_copy = bytes(self.audio_buffer)
            
            try:
                if self.encoding.lower() == "ulaw" and hasattr(self, '_wav_file_handle'):
                    # Use custom u-law writing
                    self._write_ulaw_audio_data(buffer_copy)
                elif self.wav_file:
                    # Use standard wave module
                    self.wav_file.writeframes(buffer_copy)
                else:
                    self.logger.error("No WAV file handle available for writing final data")
            except Exception as e:
                self.logger.error(f"Error writing final audio data: {e}")
        
        # Clear the buffer (for both modes)
        self.audio_buffer = bytearray()

        # Close the WAV file (only if not buffer-only)
        if not self.buffer_only:
            if self.encoding.lower() == "ulaw" and hasattr(self, '_wav_file_handle'):
                self._close_ulaw_wav_file()
            elif self.wav_file:
                self.wav_file.close()
                self.wav_file = None

        self.recording = False

        if self.buffer_only:
            self.logger.info(
                f"Finalized audio buffering for conversation {self.conversation_id} (buffer size: {len(self.audio_buffer)} bytes)"
            )
        else:
            self.logger.info(
                f"Finalized audio recording for conversation {self.conversation_id} at {self.file_path}"
            )

        return str(self.file_path) if self.file_path else None

    def get_buffered_audio(self) -> Optional[bytes]:
        """
        Get the current buffered audio data without writing to file.
        
        This method is useful in buffer-only mode to access the accumulated audio data.
        
        Returns:
            The buffered audio data as bytes, or None if no data is available
        """
        if self.audio_buffer and len(self.audio_buffer) > 0:
            return bytes(self.audio_buffer)
        return None

    def get_buffer_size(self) -> int:
        """
        Get the current size of the audio buffer.
        
        Returns:
            Number of bytes currently in the buffer
        """
        return len(self.audio_buffer)

    def clear_buffer(self) -> None:
        """
        Clear the audio buffer.
        
        This method is useful for resetting the buffer without finalizing the recording.
        """
        self.audio_buffer = bytearray()
        self.logger.debug(f"Cleared audio buffer for conversation {self.conversation_id}")

    def trigger_audio_ready_callback(self) -> bool:
        """
        Manually trigger the audio ready callback with current buffer data.
        
        This is useful when you want to process audio immediately without waiting
        for silence detection.
        
        Returns:
            True if callback was triggered, False if no callback or no data
        """
        if self.on_audio_ready and self.audio_buffer:
            audio_data = self.get_buffered_audio()
            if audio_data:
                try:
                    self.on_audio_ready(self.conversation_id, audio_data)
                    return True
                except Exception as e:
                    self.logger.error(f"Error in on_audio_ready callback: {e}")
        return False


def save_audio_to_file(
    audio_data: bytes,
    file_path: str,
    sample_rate: int = 8000,
    bit_depth: int = 8,
    channels: int = 1,
    encoding: str = "ulaw",
) -> str:
    """
    Save audio data to a WAV file.

    Args:
        audio_data: Audio data bytes to save
        file_path: Path to save the WAV file
        sample_rate: Audio sample rate in Hz (default: 8000)
        bit_depth: Audio bit depth (default: 8)
        channels: Number of audio channels (default: 1)
        encoding: Audio encoding format (default: 'ulaw')

    Returns:
        Path to the saved WAV file
    """
    # Ensure directory exists
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    # Create WAV file
    with wave.open(file_path, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(bit_depth // 8)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data)

    return file_path


def create_test_audio_file(
    output_path: str,
    duration_seconds: float = 3.0,
    sample_rate: int = 8000,
    bit_depth: int = 8,
    channels: int = 1,
    encoding: str = "ulaw",
    logger: Optional[logging.Logger] = None,
) -> str:
    """
    Create a test audio file with a simple tone for debugging audio format issues.
    
    Args:
        output_path: Path to save the test audio file
        duration_seconds: Duration of the test audio in seconds
        sample_rate: Audio sample rate in Hz
        bit_depth: Audio bit depth
        channels: Number of audio channels
        encoding: Audio encoding format
        logger: Optional logger instance
        
    Returns:
        Path to the created test audio file
    """
    try:
        import math
        
        # Create a simple sine wave tone at 440 Hz (A note)
        frequency = 440.0
        num_samples = int(sample_rate * duration_seconds)
        
        if encoding.lower() == "ulaw":
            # Generate u-law encoded test tone
            audio_data = bytearray()
            for i in range(num_samples):
                # Generate sine wave
                sample = math.sin(2 * math.pi * frequency * i / sample_rate)
                # Convert to 16-bit PCM range (-32768 to 32767)
                pcm_sample = int(sample * 16384)  # Scale to avoid clipping
                
                # Convert to u-law
                converter = AudioConverter(logger)
                ulaw_byte = converter._linear_to_ulaw(pcm_sample)
                audio_data.append(ulaw_byte)
                
        elif encoding.lower() == "pcm":
            # Generate PCM test tone
            if bit_depth == 16:
                audio_data = bytearray()
                for i in range(num_samples):
                    # Generate sine wave
                    sample = math.sin(2 * math.pi * frequency * i / sample_rate)
                    # Convert to 16-bit PCM range (-32768 to 32767)
                    pcm_sample = int(sample * 16384)  # Scale to avoid clipping
                    # Pack as little-endian 16-bit
                    audio_data.extend(struct.pack('<h', pcm_sample))
            else:  # 8-bit PCM
                audio_data = bytearray()
                for i in range(num_samples):
                    # Generate sine wave
                    sample = math.sin(2 * math.pi * frequency * i / sample_rate)
                    # Convert to 8-bit unsigned PCM range (0 to 255)
                    pcm_sample = int((sample + 1) * 127.5)
                    audio_data.append(pcm_sample)
        else:
            raise ValueError(f"Unsupported encoding: {encoding}")
        
        # Create WAV file
        converter = AudioConverter(logger)
        wav_data = converter.pcm_to_wav(
            bytes(audio_data),
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            channels=channels,
            encoding=encoding
        )
        
        # Save to file
        with open(output_path, 'wb') as f:
            f.write(wav_data)
        
        if logger:
            logger.info(f"Created test audio file: {output_path}")
            logger.info(f"Format: {sample_rate}Hz, {bit_depth}bit, {channels} channel(s), {encoding}")
            logger.info(f"Duration: {duration_seconds}s, Size: {len(wav_data)} bytes")
        
        return output_path
        
    except Exception as e:
        if logger:
            logger.error(f"Error creating test audio file: {e}")
        raise


def analyze_audio_quality(audio_path: Path, logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
    """
    Analyze audio file quality and detect potential issues.
    
    Args:
        audio_path: Path to the audio file to analyze
        logger: Optional logger instance
        
    Returns:
        Dictionary containing audio quality metrics and potential issues
    """
    try:
        converter = AudioConverter(logger)
        audio_info = converter.analyze_audio_file(audio_path)
        
        if "error" in audio_info:
            return {"error": audio_info["error"]}
        
        # Read audio data for analysis
        with wave.open(str(audio_path), "rb") as wav_file:
            audio_data = wav_file.readframes(wav_file.getnframes())
        
        # Analyze audio characteristics
        quality_metrics = {
            "file_info": audio_info,
            "quality_issues": [],
            "recommendations": []
        }
        
        # Check for common quality issues
        if audio_info["sample_rate"] != 8000:
            quality_metrics["quality_issues"].append(f"Non-standard sample rate: {audio_info['sample_rate']}Hz (expected 8000Hz)")
            quality_metrics["recommendations"].append("Convert to 8kHz for telephony compatibility")
        
        if audio_info["channels"] != 1:
            quality_metrics["quality_issues"].append(f"Non-mono audio: {audio_info['channels']} channels (expected 1)")
            quality_metrics["recommendations"].append("Convert to mono for telephony compatibility")
        
        if audio_info["bit_depth"] != 8:
            quality_metrics["quality_issues"].append(f"Non-standard bit depth: {audio_info['bit_depth']}bit (expected 8bit)")
            quality_metrics["recommendations"].append("Convert to 8-bit for telephony compatibility")
        
        # Analyze audio data patterns
        if len(audio_data) > 0:
            # Check for silence patterns
            silence_bytes = sum(1 for byte in audio_data if byte in [0xFF, 0x00])
            silence_percentage = (silence_bytes / len(audio_data)) * 100
            
            if silence_percentage > 90:
                quality_metrics["quality_issues"].append(f"High silence content: {silence_percentage:.1f}%")
                quality_metrics["recommendations"].append("Check audio input source and encoding")
            
            # Check for data patterns that might indicate corruption
            unique_bytes = len(set(audio_data))
            if unique_bytes < 10:
                quality_metrics["quality_issues"].append(f"Low data variety: only {unique_bytes} unique byte values")
                quality_metrics["recommendations"].append("Audio may be corrupted or improperly encoded")
            
            # Check for repeated patterns that might indicate encoding issues
            if len(audio_data) > 100:
                sample = audio_data[:100]
                pattern_length = 1
                for i in range(1, min(50, len(sample) // 2)):
                    if sample[:i] * (len(sample) // i) == sample[:(len(sample) // i) * i]:
                        pattern_length = i
                        break
                
                if pattern_length > 1:
                    quality_metrics["quality_issues"].append(f"Repeated pattern detected: {pattern_length} byte pattern")
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
