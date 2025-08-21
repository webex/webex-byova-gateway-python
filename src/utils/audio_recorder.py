"""
Audio recorder utility class for the Webex Contact Center BYOVA Gateway.

This module provides audio recording functionality that integrates with AudioBuffer
for audio data management and silence detection.
"""

import logging
import os
import struct
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional

from .audio_buffer import AudioBuffer


class AudioRecorder:
    """
    Audio recorder utility class for recording caller audio to WAV files.

    Features:
    - Records audio data to WAV files
    - Integrates with AudioBuffer for audio data management
    - Automatically finalizes recording after silence detection
    - Supports various audio formats and sample rates
    - File management and cleanup
    """

    def __init__(
        self,
        conversation_id: str,
        audio_buffer: AudioBuffer,
        output_dir: str = "logs",
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
            audio_buffer: AudioBuffer instance to use for audio data management
            output_dir: Directory to save WAV files (default: 'logs')
            sample_rate: Audio sample rate in Hz
            bit_depth: Audio bit depth
            channels: Number of audio channels
            encoding: Audio encoding format
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
        self.conversation_id = conversation_id
        self.audio_buffer = audio_buffer
        self.output_dir = Path(output_dir)
        self.sample_rate = sample_rate
        self.bit_depth = bit_depth
        self.channels = channels
        self.encoding = encoding

        # Internal state
        self.wav_file = None
        self.recording = False
        self.file_path = None
        self._wav_file_handle = None
        self._data_start_pos = 0
        self._riff_size_pos = 0

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            f"AudioRecorder initialized for conversation {conversation_id} "
            f"(output: {output_dir}, format: {sample_rate}Hz, {bit_depth}bit, "
            f"{channels} channel(s), {encoding})"
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

        # Reset recording state
        self.recording = True

        self.logger.info(
            f"Started recording audio for conversation {self.conversation_id} to {self.file_path}"
        )

    def add_audio_data(self, audio_data: bytes, encoding: str = "ulaw") -> bool:
        """
        Add audio data to the current recording.

        This method delegates to the AudioBuffer for audio data management
        and silence detection, then writes to the WAV file if recording.

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

        # Delegate to AudioBuffer for audio data management and silence detection
        buffer_continues = self.audio_buffer.add_audio_data(audio_data, encoding)
        
        # If buffer triggered callback (silence detected), finalize recording
        if not buffer_continues and self.recording:
            self.logger.info(
                f"Silence detected by AudioBuffer, finalizing recording for conversation {self.conversation_id}"
            )
            self.finalize_recording()
            return False

        # If we're recording and have audio data, write to WAV file
        if self.recording and self.audio_buffer.get_buffer_size() > 0:
            # Get the buffered audio data
            buffered_audio = self.audio_buffer.get_buffered_audio()
            if buffered_audio:
                try:
                    if self.encoding.lower() == "ulaw" and hasattr(self, '_wav_file_handle'):
                        # Use custom u-law writing
                        self._write_ulaw_audio_data(buffered_audio)
                        bytes_written = len(buffered_audio)
                        self.logger.debug(
                            f"Wrote {bytes_written} bytes to u-law WAV file {self.file_path}"
                        )
                    elif self.wav_file:
                        # Use standard wave module
                        bytes_written = len(buffered_audio)
                        self.wav_file.writeframes(buffered_audio)
                        self.logger.debug(
                            f"Wrote {bytes_written} bytes to WAV file {self.file_path}"
                        )
                    else:
                        self.logger.error("No WAV file handle available for writing")
                        
                except Exception as e:
                    self.logger.error(f"Error writing to WAV file: {e}")

        return True

    def check_silence_timeout(self) -> bool:
        """
        Check if the recording should be finalized due to silence timeout.
        This method delegates to the AudioBuffer for silence detection.
        
        Returns:
            True if recording continues, False if recording was finalized due to silence
        """
        # Delegate to AudioBuffer for silence detection
        buffer_continues = self.audio_buffer.check_silence_timeout()
        
        # If buffer triggered callback (silence detected), finalize recording
        if not buffer_continues and self.recording:
            self.logger.info(
                f"Silence timeout detected by AudioBuffer, finalizing recording for conversation {self.conversation_id}"
            )
            self.finalize_recording()
            return False
            
        return True

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

    def finalize_recording(self) -> Optional[str]:
        """
        Finalize the current recording and close the WAV file.

        Returns:
            The path to the saved WAV file, or None if no recording was in progress
        """
        if not self.recording:
            return None

        # Write any remaining data from the buffer
        if self.audio_buffer.get_buffer_size() > 0:
            buffered_audio = self.audio_buffer.get_buffered_audio()
            if buffered_audio:
                try:
                    if self.encoding.lower() == "ulaw" and hasattr(self, '_wav_file_handle'):
                        # Use custom u-law writing
                        self._write_ulaw_audio_data(buffered_audio)
                    elif self.wav_file:
                        # Use standard wave module
                        self.wav_file.writeframes(buffered_audio)
                    else:
                        self.logger.error("No WAV file handle available for writing final data")
                except Exception as e:
                    self.logger.error(f"Error writing final audio data: {e}")

        # Close the WAV file
        if self.encoding.lower() == "ulaw" and hasattr(self, '_wav_file_handle'):
            self._close_ulaw_wav_file()
        elif self.wav_file:
            self.wav_file.close()
            self.wav_file = None

        self.recording = False

        self.logger.info(
            f"Finalized audio recording for conversation {self.conversation_id} at {self.file_path}"
        )

        return str(self.file_path) if self.file_path else None

    def is_recording(self) -> bool:
        """
        Check if audio recording is currently active.
        
        Returns:
            True if recording is active, False otherwise
        """
        return self.recording

    def get_recording_path(self) -> Optional[str]:
        """
        Get the path to the current recording file.
        
        Returns:
            Path to the recording file, or None if no recording in progress
        """
        return str(self.file_path) if self.file_path else None

    def get_recording_stats(self) -> dict:
        """
        Get statistics about the current recording session.
        
        Returns:
            Dictionary containing recording statistics
        """
        return {
            "conversation_id": self.conversation_id,
            "is_recording": self.recording,
            "file_path": str(self.file_path) if self.file_path else None,
            "output_dir": str(self.output_dir),
            "sample_rate": self.sample_rate,
            "bit_depth": self.bit_depth,
            "channels": self.channels,
            "encoding": self.encoding,
            "buffer_stats": self.audio_buffer.get_buffering_stats()
        }

    def stop_recording(self) -> Optional[str]:
        """
        Stop the current recording session.
        
        This is an alias for finalize_recording() for consistency.
        
        Returns:
            The path to the saved WAV file, or None if no recording was in progress
        """
        return self.finalize_recording()

    def pause_recording(self) -> None:
        """
        Pause the current recording session.
        
        Note: This is a placeholder for future implementation.
        Current implementation doesn't support pausing.
        """
        self.logger.warning("Pause recording not implemented in current version")

    def resume_recording(self) -> None:
        """
        Resume a paused recording session.
        
        Note: This is a placeholder for future implementation.
        Current implementation doesn't support pausing.
        """
        self.logger.warning("Resume recording not implemented in current version")
