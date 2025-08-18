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
            with wave.open(str(audio_path), "rb") as wav_file:
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
                n_frames = wav_file.getnframes()
                compression_type = wav_file.getcomptype()
                bit_depth = sample_width * 8
                duration = n_frames / sample_rate if sample_rate > 0 else 0

                return {
                    "file_path": str(audio_path),
                    "file_size": file_size,
                    "channels": channels,
                    "sample_width": sample_width,
                    "sample_rate": sample_rate,
                    "bit_depth": bit_depth,
                    "n_frames": n_frames,
                    "duration": duration,
                    "compression_type": compression_type,
                    "is_wxcc_compatible": (
                        sample_rate == 8000 and 
                        bit_depth == 8 and 
                        channels == 1 and 
                        compression_type == b"NONE"
                    )
                }

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
                # Read and return the file as-is
                with wave.open(str(audio_path), "rb") as wav_file:
                    return wav_file.readframes(wav_file.getnframes())

            self.logger.info(f"Converting audio file {audio_path} to WXCC-compatible format")
            self.logger.info(
                f"Original format: {audio_info['sample_rate']}Hz, {audio_info['bit_depth']}bit, "
                f"{audio_info['channels']} channel(s), compression: {audio_info['compression_type']}"
            )

            # Read the original audio data
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
        sample_rate: int = 8000,
        bit_depth: int = 8,
        channels: int = 1,
        encoding: str = "ulaw",
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """
        Initialize the audio recorder.

        Args:
            conversation_id: Unique identifier for the conversation
            output_dir: Directory to save WAV files (default: 'logs')
            silence_threshold: Amplitude threshold for silence detection
            silence_duration: Amount of silence (in seconds) before finalizing the recording
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
        self.sample_rate = sample_rate
        self.bit_depth = bit_depth
        self.channels = channels
        self.encoding = encoding

        # Internal state
        self.audio_buffer = bytearray()
        self.wav_file = None
        self.recording = False
        self.last_audio_time = 0
        self.file_path = None

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            f"AudioRecorder initialized for conversation {conversation_id} "
            f"(silence threshold: {silence_threshold}, duration: {silence_duration}s)"
        )

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

        # Generate filename with timestamp and conversation ID
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"caller_audio_{self.conversation_id}_{timestamp}.wav"
        self.file_path = self.output_dir / filename

        # Set up WAV file
        self.wav_file = wave.open(str(self.file_path), "wb")
        self.wav_file.setnchannels(self.channels)
        self.wav_file.setsampwidth(self.bit_depth // 8)
        self.wav_file.setframerate(self.sample_rate)

        # Reset state
        self.audio_buffer = bytearray()
        self.recording = True
        self.last_audio_time = time.time()

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

        if not self.recording:
            self.start_recording()

        # Update the last audio time
        self.last_audio_time = time.time()
        # Log audio data characteristics
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                f"Adding {len(audio_data)} bytes of {encoding} audio data to recording"
            )
            self.logger.debug(f"First 10 bytes: {audio_data[:10]}")

        # Add audio data to buffer
        self.audio_buffer.extend(audio_data)
        self.logger.debug(
            f"Buffer size after adding data: {len(self.audio_buffer)} bytes"
        )
        # Check if we have enough data to process
        if (
            len(self.audio_buffer) >= 640
        ):  # Process in smaller chunks for more frequent writes
            # Write to WAV file - ensure we have a copy of the buffer before clearing
            buffer_copy = bytes(self.audio_buffer)
            if self.wav_file:
                try:
                    bytes_written = len(buffer_copy)
                    self.wav_file.writeframes(buffer_copy)
                    self.logger.debug(
                        f"Wrote {bytes_written} bytes to WAV file {self.file_path}"
                    )
                except Exception as e:
                    self.logger.error(f"Error writing to WAV file: {e}")

            # Check for silence
            if self.detect_silence(buffer_copy):
                # Check if silence duration threshold exceeded
                silence_time = time.time() - self.last_audio_time
                if silence_time >= self.silence_duration:
                    self.logger.info(
                        f"Silence detected for {silence_time:.2f}s in conversation {self.conversation_id}, finalizing recording"
                    )
                    self.finalize_recording()
                    return False
            else:
                # Reset the last audio time as we detected non-silence
                self.last_audio_time = time.time()

            # Clear the buffer after processing
            self.audio_buffer = bytearray()

        return True

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
            # Count how many bytes differ significantly from 0xFF (silence in u-law)
            # U-law silence is typically 0xFF, so we check for values that differ from that
            diff_threshold = (
                10  # Smaller threshold means more sensitive silence detection
            )
            non_silence_count = sum(
                1 for byte in audio_data if abs(byte - 0xFF) > diff_threshold
            )
            # Calculate percentage of non-silent samples
            if len(audio_data) > 0:
                non_silence_percentage = (non_silence_count / len(audio_data)) * 100
                self.logger.debug(
                    f"Detected {non_silence_percentage:.2f}% non-silent samples"
                )

                # If less than 10% of samples are non-silent, consider it silence
                is_silence = non_silence_percentage < 10
                if is_silence:
                    self.logger.debug("Audio segment detected as silence")
                else:
                    self.logger.debug("Audio segment contains speech/audio")

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
            return None

        # Write any remaining data
        if self.audio_buffer and self.wav_file:
            self.wav_file.writeframes(bytes(self.audio_buffer))
            self.audio_buffer = bytearray()

        # Close the WAV file
        if self.wav_file:
            self.wav_file.close()
            self.wav_file = None

        self.recording = False

        self.logger.info(
            f"Finalized audio recording for conversation {self.conversation_id} at {self.file_path}"
        )

        return str(self.file_path) if self.file_path else None


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
