"""
Audio buffer utility class for the Webex Contact Center BYOVA Gateway.

This module provides audio buffering functionality with silence detection
that can be used independently of audio recording.
"""

import logging
import time
from typing import Optional, Dict, Any


class AudioBuffer:
    """
    Audio buffer utility class for buffering caller audio with silence detection.

    Features:
    - Buffers audio data in memory
    - Implements silence detection
    - Automatically triggers callback when silence threshold is reached
    - Supports various audio formats and sample rates
    - Configurable buffer size limits
    """

    def __init__(
        self,
        conversation_id: str,
        max_buffer_size: int = 1024 * 1024,  # 1MB default
        silence_threshold: int = 3000,
        silence_duration: float = 2.0,
        quiet_threshold: int = 20,
        sample_rate: int = 8000,
        bit_depth: int = 8,
        channels: int = 1,
        encoding: str = "ulaw",
        on_audio_ready: Optional[callable] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """
        Initialize the audio buffer.

        Args:
            conversation_id: Unique identifier for the conversation
            max_buffer_size: Maximum buffer size in bytes (default: 1MB)
            silence_threshold: Amplitude threshold for silence detection
            silence_duration: Amount of silence (in seconds) before triggering callback
            quiet_threshold: How far from 127 (quiet background) to consider "silence" (default: 20)
            sample_rate: Audio sample rate in Hz
            bit_depth: Audio bit depth
            channels: Number of audio channels
            encoding: Audio encoding format
            on_audio_ready: Callback function called when silence threshold is reached
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
        self.conversation_id = conversation_id
        self.max_buffer_size = max_buffer_size
        self.silence_threshold = silence_threshold
        self.silence_duration = silence_duration
        self.quiet_threshold = quiet_threshold
        self.sample_rate = sample_rate
        self.bit_depth = bit_depth
        self.channels = channels
        self.encoding = encoding
        self.on_audio_ready = on_audio_ready

        # Internal state
        self.audio_buffer = bytearray()
        self.buffering = False
        self.last_audio_time = 0
        self.waiting_for_speech = True  # Wait for first non-silence before starting buffering
        self.speech_detected = False    # Track if we've ever detected speech

        self.logger.info(
            f"AudioBuffer initialized for conversation {conversation_id} "
            f"(silence threshold: {silence_threshold}, duration: {silence_duration}s, "
            f"quiet threshold: {quiet_threshold}, max buffer size: {max_buffer_size} bytes, "
            f"waiting for speech: {self.waiting_for_speech})"
        )

    def start_buffering(self) -> None:
        """
        Start a new audio buffering session.

        If buffering is already in progress, it will be reset first.
        """
        if self.buffering:
            self.logger.info(
                f"Resetting previous buffering session for {self.conversation_id}"
            )
            self.clear_buffer()

        # Reset state
        self.audio_buffer = bytearray()
        self.buffering = True
        self.last_audio_time = time.time()
        self.waiting_for_speech = True   # We're waiting for speech to start
        self.speech_detected = False     # Haven't detected speech yet

        self.logger.info(
            f"Started buffering audio for conversation {self.conversation_id}"
        )

    def add_audio_data(self, audio_data: bytes, encoding: str = "ulaw") -> bool:
        """
        Add audio data to the current buffer.

        Args:
            audio_data: Audio data bytes to add to the buffer
            encoding: Format of the input audio data (default: 'ulaw')

        Returns:
            True if buffering continues, False if callback was triggered due to silence
        """
        if not audio_data:
            self.logger.warning(
                f"Received empty audio data for conversation {self.conversation_id}"
            )
            return True

        # Log audio data characteristics
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                f"Adding {len(audio_data)} bytes of {encoding} audio data to buffer"
            )
            self.logger.debug(f"First 10 bytes: {audio_data[:10]}")
            # Log hex representation for debugging
            hex_preview = audio_data[:20].hex()
            self.logger.debug(f"Audio data hex preview: {hex_preview}...")

        # Convert audio data to the buffer format if needed
        processed_audio = self._convert_audio_to_buffer_format(audio_data, encoding)
        
        # Check buffer size limit
        if len(self.audio_buffer) + len(processed_audio) > self.max_buffer_size:
            self.logger.warning(
                f"Buffer size limit reached ({self.max_buffer_size} bytes) for conversation {self.conversation_id}, "
                f"truncating audio data"
            )
            # Truncate to fit within buffer limit
            remaining_space = self.max_buffer_size - len(self.audio_buffer)
            if remaining_space > 0:
                processed_audio = processed_audio[:remaining_space]
            else:
                # Buffer is full, can't add more data
                return True

        # Add audio data to buffer
        self.audio_buffer.extend(processed_audio)
        self.logger.debug(
            f"Buffer size after adding data: {len(self.audio_buffer)} bytes"
        )
        
        # Check if we have enough data to process
        # Use frame-aligned buffer sizes based on encoding and bit depth
        frame_size = self._get_frame_size()
        if len(self.audio_buffer) >= frame_size:
            # Check for silence first to determine if we should start buffering
            is_silence = self.detect_silence(processed_audio)
            
            if self.waiting_for_speech:
                if is_silence:
                    # Still waiting for speech, don't start buffering yet
                    self.logger.debug(
                        f"Still waiting for speech in conversation {self.conversation_id}, "
                        f"silence detected in audio segment"
                    )
                    return True
                else:
                    # Speech detected! Start buffering now
                    self.waiting_for_speech = False
                    self.speech_detected = True
                    self.last_audio_time = time.time()
                    self.buffering = True
                    self.logger.info(
                        f"Speech detected! Starting buffering for conversation {self.conversation_id}"
                    )
            
            # At this point, we're either already buffering or just started
            if self.buffering:
                # Check for silence after buffering has started
                if is_silence:
                    # Check if silence duration threshold exceeded
                    silence_time = time.time() - self.last_audio_time
                    self.logger.debug(
                        f"Silence detected in audio segment, silence duration so far: {silence_time:.2f}s "
                        f"(threshold: {self.silence_duration}s)"
                    )
                    if silence_time >= self.silence_duration:
                        self.logger.info(
                            f"Silence detected for {silence_time:.2f}s in conversation {self.conversation_id}, "
                            f"triggering audio ready callback"
                        )
                        
                        # Get the audio data before clearing (make a copy)
                        audio_data = bytes(self.audio_buffer) if self.audio_buffer else None
                        
                        # Clear the buffer before triggering callback (to prevent double-processing)
                        self.clear_buffer()
                        
                        # Trigger the callback
                        if audio_data:
                            self._trigger_audio_ready_callback(audio_data)
                        
                        # Reset the buffer to waiting for speech state after callback
                        self.reset_after_callback()
                        
                        return False
                else:
                    # Reset the last audio time as we detected non-silence
                    self.logger.debug(
                        f"Non-silence detected in audio segment, resetting silence timer for {self.conversation_id}"
                    )
                    self.last_audio_time = time.time()

        return True

    def check_silence_timeout(self) -> bool:
        """
        Check if the buffer should trigger callback due to silence timeout.
        This method can be called periodically to check for silence even when no audio data is received.
        
        Returns:
            True if buffering continues, False if callback was triggered due to silence
        """
        if not self.buffering:
            # If we're not buffering yet, check if we should start buffering
            if self.waiting_for_speech:
                self.logger.debug(
                    f"Still waiting for speech in conversation {self.conversation_id}, "
                    f"no buffering started yet"
                )
                return True
            return True
            
        # Check if we've exceeded the silence duration
        current_time = time.time()
        silence_time = current_time - self.last_audio_time
        
        if silence_time >= self.silence_duration:
            self.logger.info(
                f"Silence timeout reached ({silence_time:.2f}s) for conversation {self.conversation_id}, "
                f"triggering audio ready callback"
            )
            
            # Get the audio data before clearing (make a copy)
            audio_data = bytes(self.audio_buffer) if self.audio_buffer else None
            
            # Clear the buffer
            self.clear_buffer()
            
            # Trigger the callback
            if audio_data:
                self._trigger_audio_ready_callback(audio_data)
            
            # Reset the buffer to waiting for speech state after callback
            self.reset_after_callback()
            
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

    def _convert_audio_to_buffer_format(self, audio_data: bytes, input_encoding: str) -> bytes:
        """
        Convert incoming audio data to the buffer format.
        
        Args:
            audio_data: Raw audio data bytes
            input_encoding: Encoding of the input audio data
            
        Returns:
            Audio data converted to the buffer format
        """
        try:
            # If input encoding matches buffer encoding, return as-is
            if input_encoding.lower() == self.encoding.lower():
                self.logger.debug(f"Audio format matches buffer format ({input_encoding})")
                return audio_data
            
            # For now, return as-is and log a warning for unsupported conversions
            # This can be enhanced later with proper format conversion
            self.logger.warning(
                f"Audio format conversion not implemented: {input_encoding} -> {self.encoding}, "
                f"using original data"
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

    def _trigger_audio_ready_callback(self, audio_data: bytes) -> None:
        """
        Internal method to trigger the audio ready callback.
        
        Args:
            audio_data: The audio data that is ready for processing
        """
        if self.on_audio_ready and audio_data:
            try:
                self.on_audio_ready(self.conversation_id, audio_data)
                self.logger.debug(
                    f"Successfully triggered audio ready callback for conversation {self.conversation_id}"
                )
            except Exception as e:
                self.logger.error(f"Error in on_audio_ready callback: {e}")

    def get_buffered_audio(self) -> Optional[bytes]:
        """
        Get the current buffered audio data without clearing the buffer.
        
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

    def is_buffer_full(self) -> bool:
        """
        Check if the audio buffer has reached its maximum capacity.
        
        Returns:
            True if buffer is at or above capacity, False otherwise
        """
        return len(self.audio_buffer) >= self.max_buffer_size

    def clear_buffer(self) -> None:
        """
        Clear the audio buffer.
        
        This method is useful for resetting the buffer without triggering callbacks.
        """
        self.audio_buffer = bytearray()
        self.logger.debug(f"Cleared audio buffer for conversation {self.conversation_id}")

    def reset_after_callback(self) -> None:
        """
        Reset the buffer to its initial state after a callback has been triggered.
        
        This method should be called after the audio ready callback to prepare
        the buffer for detecting the next speech segment.
        """
        self.buffering = False
        self.waiting_for_speech = True
        self.speech_detected = False
        self.last_audio_time = 0.0
        self.clear_buffer()
        self.logger.info(
            f"Reset buffer to waiting for speech state for conversation {self.conversation_id}"
        )

    def stop_buffering(self) -> None:
        """
        Stop the current buffering session.
        
        This will clear the buffer and reset the buffering state.
        """
        self.buffering = False
        self.waiting_for_speech = True
        self.speech_detected = False
        self.clear_buffer()
        self.logger.info(f"Stopped buffering for conversation {self.conversation_id}")

    def is_buffering(self) -> bool:
        """
        Check if audio buffering is currently active.
        
        Returns:
            True if buffering is active, False otherwise
        """
        return self.buffering

    def get_buffering_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the current buffering session.
        
        Returns:
            Dictionary containing buffering statistics
        """
        return {
            "conversation_id": self.conversation_id,
            "is_buffering": self.buffering,
            "waiting_for_speech": self.waiting_for_speech,
            "speech_detected": self.speech_detected,
            "buffer_size": len(self.audio_buffer),
            "max_buffer_size": self.max_buffer_size,
            "buffer_utilization": (len(self.audio_buffer) / self.max_buffer_size) * 100 if self.max_buffer_size > 0 else 0,
            "last_audio_time": self.last_audio_time,
            "silence_threshold": self.silence_threshold,
            "silence_duration": self.silence_duration,
            "quiet_threshold": self.quiet_threshold,
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "channels": self.channels,
            "encoding": self.encoding
        }

    def trigger_audio_ready_callback_manually(self) -> bool:
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
