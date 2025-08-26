"""
Audio Logger utility class for the Webex Contact Center BYOVA Gateway.

This module provides audio logging functionality that can be used by connectors
to log conversational audio to WAV files for debugging and analysis purposes.
"""

import logging
import os
import struct
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from .audio_utils import AudioConverter


class AudioLogger:
    """
    Audio Logger utility class for logging conversational audio to WAV files.

    Features:
    - Logs incoming WxCC audio and outgoing AWS Lex audio
    - Creates WAV files with proper headers
    - Handles audio format conversion
    - Manages file size limits and splitting
    - Generates timestamped filenames
    - Provides cleanup functionality
    """

    def __init__(
        self,
        config: Dict[str, Any],
        logger: Optional[logging.Logger] = None,
    ) -> None:
        """
        Initialize the AudioLogger.

        Args:
            config: Configuration dictionary containing:
                - output_dir: Directory to save WAV files
                - filename_format: Format string for filenames
                - max_file_size: Maximum file size in bytes
                - sample_rate: Audio sample rate in Hz
                - bit_depth: Audio bit depth
                - channels: Number of audio channels
                - encoding: Audio encoding format
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
        
        # Extract configuration with defaults
        self.output_dir = Path(config.get('output_dir', 'logs/audio_recordings'))
        self.filename_format = config.get('filename_format', '{conversation_id}_{timestamp}_{source}.wav')
        self.max_file_size = config.get('max_file_size', 10485760)  # 10MB default
        self.sample_rate = config.get('sample_rate', 8000)
        self.bit_depth = config.get('bit_depth', 8)
        self.channels = config.get('channels', 1)
        self.encoding = config.get('encoding', 'ulaw')
        
        # Initialize audio converter
        self.audio_converter = AudioConverter(logger=self.logger)
        
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(
            f"AudioLogger initialized - output: {self.output_dir}, "
            f"max size: {self.max_file_size} bytes, format: {self.sample_rate}Hz, "
            f"{self.bit_depth}bit, {self.channels} channel(s), {self.encoding}"
        )

    def log_audio(self, conversation_id: str, audio_data: bytes, source: str, 
                  encoding: str = None, sample_rate: int = None, bit_depth: int = None, 
                  channels: int = None) -> Optional[str]:
        """
        Log audio data to a WAV file.

        Args:
            conversation_id: Unique conversation identifier
            audio_data: Raw audio data
            source: Source identifier for the audio (e.g., 'wxcc', 'aws', 'user', 'bot')
            encoding: Audio encoding (e.g., 'ulaw', 'pcm', 'alaw'). If None, uses default from config
            sample_rate: Audio sample rate. If None, uses default from config
            bit_depth: Audio bit depth. If None, uses default from config
            channels: Number of audio channels. If None, uses default from config

        Returns:
            Path to the created WAV file, or None if logging failed
        """
        if not audio_data or not conversation_id:
            self.logger.warning(f"Invalid audio data or conversation ID for audio logging")
            return None

        try:
            # Use provided parameters or fall back to defaults
            audio_encoding = encoding or self.encoding
            audio_sample_rate = sample_rate or self.sample_rate
            audio_bit_depth = bit_depth or self.bit_depth
            audio_channels = channels or self.channels
            
            # Generate filename
            filename = self._generate_filename(conversation_id, source)
            file_path = self.output_dir / filename
            
            # Convert audio to WAV format
            wav_audio = self._convert_audio_to_wav(audio_data, audio_encoding, audio_sample_rate, 
                                                  audio_bit_depth, audio_channels)
            
            # Handle file size limits
            if len(wav_audio) > self.max_file_size:
                return self._split_and_save_large_audio(wav_audio, file_path, conversation_id, source)
            else:
                # Save single file
                self._save_wav_file(file_path, wav_audio)
                self.logger.debug(f"Logged {source} audio to {file_path}")
                return str(file_path)
                
        except Exception as e:
            self.logger.error(f"Failed to log {source} audio for conversation {conversation_id}: {e}")
            return None

    def cleanup(self, conversation_id: str) -> None:
        """
        Clean up resources for a specific conversation.

        Args:
            conversation_id: Conversation identifier to clean up
        """
        try:
            # This could involve removing temporary files or resetting state
            # For now, just log the cleanup
            self.logger.debug(f"Cleaned up audio logging resources for conversation {conversation_id}")
        except Exception as e:
            self.logger.error(f"Error during audio logging cleanup for conversation {conversation_id}: {e}")

    def _generate_timestamp(self) -> str:
        """
        Generate a human-readable timestamp for filenames.

        Returns:
            Timestamp string in format YYYYMMDD_HHMMSS
        """
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _generate_filename(self, conversation_id: str, source: str) -> str:
        """
        Generate filename for audio files.

        Args:
            conversation_id: Conversation identifier
            source: Source identifier for the audio

        Returns:
            Filename string
        """
        timestamp = self._generate_timestamp()
        return self.filename_format.format(
            conversation_id=conversation_id,
            timestamp=timestamp,
            source=source
        )

    def _convert_audio_to_wav(self, audio_data: bytes, encoding: str, sample_rate: int, 
                              bit_depth: int, channels: int) -> bytes:
        """
        Convert audio data to WAV format.

        Args:
            audio_data: Raw audio data
            encoding: Audio encoding (e.g., 'ulaw', 'pcm', 'alaw')
            sample_rate: Audio sample rate
            bit_depth: Audio bit depth
            channels: Number of audio channels

        Returns:
            WAV format audio data
        """
        return self.audio_converter.pcm_to_wav(
            audio_data,
            sample_rate=sample_rate,
            bit_depth=bit_depth,
            channels=channels,
            encoding=encoding
        )

    def _split_and_save_large_audio(self, wav_audio: bytes, base_file_path: Path, 
                                   conversation_id: str, source: str) -> List[str]:
        """
        Split large audio data into multiple files and save them.

        Args:
            wav_audio: Complete WAV audio data
            base_file_path: Base file path for the audio
            conversation_id: Conversation identifier
            source: Audio source ('wxcc' or 'aws')

        Returns:
            List of file paths for the split files
        """
        try:
            # Calculate number of parts needed
            audio_size = len(wav_audio)
            part_size = self.max_file_size
            num_parts = (audio_size + part_size - 1) // part_size  # Ceiling division
            
            file_paths = []
            
            for part_num in range(1, num_parts + 1):
                # Calculate start and end indices for this part
                start_idx = (part_num - 1) * part_size
                end_idx = min(start_idx + part_size, audio_size)
                
                # Extract audio data for this part
                part_audio = wav_audio[start_idx:end_idx]
                
                # Generate filename for this part
                timestamp = self._generate_timestamp()
                part_filename = f"{conversation_id}_{timestamp}_{source}_part{part_num}.wav"
                part_file_path = self.output_dir / part_filename
                
                # Save this part
                self._save_wav_file(part_file_path, part_audio)
                file_paths.append(str(part_file_path))
                
                self.logger.debug(f"Saved audio part {part_num}/{num_parts} to {part_file_path}")
            
            self.logger.info(f"Split large audio into {num_parts} parts for conversation {conversation_id}")
            return file_paths
            
        except Exception as e:
            self.logger.error(f"Failed to split large audio for conversation {conversation_id}: {e}")
            return []

    def _save_wav_file(self, file_path: Path, wav_audio: bytes) -> None:
        """
        Save WAV audio data to a file.

        Args:
            file_path: Path to save the file
            wav_audio: WAV format audio data
        """
        try:
            with open(file_path, 'wb') as f:
                f.write(wav_audio)
            self.logger.debug(f"Saved WAV file: {file_path} ({len(wav_audio)} bytes)")
        except Exception as e:
            self.logger.error(f"Failed to save WAV file {file_path}: {e}")
            raise

    def _create_wav_file(self, audio_data: bytes, filename: str) -> str:
        """
        Create a minimal WAV file with the given audio data.

        Args:
            audio_data: Raw audio data
            filename: Name of the file to create

        Returns:
            Path to the created file
        """
        file_path = self.output_dir / filename
        
        # Convert audio data to WAV format
        wav_audio = self.audio_converter.pcm_to_wav(
            audio_data,
            sample_rate=self.sample_rate,
            bit_depth=self.bit_depth,
            channels=self.channels,
            encoding=self.encoding
        )
        
        # Save the file
        self._save_wav_file(file_path, wav_audio)
        return str(file_path)
