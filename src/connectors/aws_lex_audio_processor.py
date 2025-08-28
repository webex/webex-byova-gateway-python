"""
AWS Lex Audio Processor for Webex Contact Center BYOVA Gateway.

This module handles all audio-related operations for the AWS Lex connector,
including buffering, logging, and format conversion.
"""

import logging
from typing import Any, Dict, List, Optional, Iterator

from ..utils.audio_buffer import AudioBuffer
from ..utils.audio_utils import convert_aws_lex_audio_to_wxcc, convert_wxcc_audio_to_lex_format
from ..utils.audio_logger import AudioLogger


class AWSLexAudioProcessor:
    """
    Handles all audio-related operations for AWS Lex connector.
    
    This class encapsulates audio buffering, logging, and format conversion
    to keep the main connector focused on business logic.
    """

    def __init__(self, config: Dict[str, Any], logger: logging.Logger):
        """
        Initialize the audio processor.

        Args:
            config: Configuration dictionary containing audio settings
            logger: Logger instance for the connector
        """
        self.logger = logger
        
        # Audio buffering configuration
        self.audio_buffering_config = config.get("audio_buffering", {
            "silence_threshold": 2000,   # Moderate sensitivity - detect silence but not too aggressively
            "silence_duration": 2.5,    # Reasonable silence duration - wait for natural speech pauses
            "quiet_threshold": 20        # Moderate quiet detection
        })
        
        # Audio buffers by conversation ID
        self.audio_buffers = {}
        
        # Initialize audio logging if configured
        self._init_audio_logging(config)
        
        self.logger.debug("Caller audio buffering is enabled")

    def _init_audio_logging(self, config: Dict[str, Any]) -> None:
        """
        Initialize audio logging functionality if configured.

        Args:
            config: Configuration dictionary
        """
        audio_logging_config = config.get('audio_logging', {})
        
        if audio_logging_config.get('enabled', False):
            try:
                # Set default values for missing configuration
                default_config = {
                    'output_dir': 'logs/audio_recordings',
                    'filename_format': '{conversation_id}_{timestamp}_{source}.wav',
                    'max_file_size': 10485760,  # 10MB
                    'sample_rate': 8000,
                    'bit_depth': 8,
                    'channels': 1,
                    'encoding': 'ulaw',
                    'log_all_audio': True  # Generic flag to enable/disable all audio logging
                }
                
                # Merge user config with defaults
                for key, value in default_config.items():
                    if key not in audio_logging_config:
                        audio_logging_config[key] = value
                
                # Initialize AudioLogger
                self.audio_logger = AudioLogger(audio_logging_config, self.logger)
                self.audio_logging_config = audio_logging_config
                
                self.logger.info("Audio logging initialized and enabled")
                
            except Exception as e:
                self.logger.error(f"Failed to initialize audio logging: {e}")
                self.logger.warning("Audio logging will be disabled due to initialization failure")
                # Don't set any audio logging attributes when disabled
        else:
            # Don't set any audio logging attributes when disabled
            self.logger.debug("Audio logging not configured or disabled")

    def init_audio_buffer(self, conversation_id: str) -> None:
        """
        Initialize audio buffer for a conversation.

        Args:
            conversation_id: Unique identifier for the conversation
        """
        if conversation_id in self.audio_buffers:
            self.logger.info(
                f"Audio buffer already exists for conversation {conversation_id}"
            )
            return

        try:
            # Get audio buffering configuration
            silence_threshold = self.audio_buffering_config.get(
                "silence_threshold", 3000
            )
            silence_duration = self.audio_buffering_config.get("silence_duration", 2.0)
            quiet_threshold = self.audio_buffering_config.get("quiet_threshold", 20)

            # Create audio buffer
            self.audio_buffers[conversation_id] = AudioBuffer(
                conversation_id=conversation_id,
                silence_threshold=silence_threshold,
                silence_duration=silence_duration,
                quiet_threshold=quiet_threshold,
                sample_rate=8000,  # WxCC compatible sample rate
                bit_depth=8,       # WxCC compatible bit depth
                channels=1,        # WxCC compatible channels
                encoding="ulaw",   # WxCC compatible encoding
                logger=self.logger,
            )

            self.logger.info(
                f"Initialized audio buffer for conversation {conversation_id} "
                f"(silence threshold: {silence_threshold}, duration: {silence_duration}s, "
                f"quiet threshold: {quiet_threshold})"
            )
        except Exception as e:
            self.logger.error(f"Failed to initialize audio buffer: {e}")
            # Don't raise the exception, continue without buffering

    def process_audio_for_buffering(self, audio_data, conversation_id: str, extract_audio_data_func) -> Dict[str, Any]:
        """
        Process audio data for buffering.

        Args:
            audio_data: Audio data to buffer (bytes, bytearray, or str)
            conversation_id: Unique identifier for the conversation
            extract_audio_data_func: Function to extract audio bytes from data

        Returns:
            Dictionary containing buffer status information:
            - silence_detected: True if silence threshold was detected
            - speech_detected: True if speech has been detected in this session
            - waiting_for_speech: True if still waiting for first speech
            - buffer_size: Current size of the buffer in bytes
        """
        if not audio_data:
            return {
                "silence_detected": False,
                "speech_detected": False,
                "waiting_for_speech": True,
                "buffer_size": 0
            }

        # Initialize buffer if not already done
        if conversation_id not in self.audio_buffers:
            self.init_audio_buffer(conversation_id)

        if conversation_id not in self.audio_buffers:
            # Initialization failed
            return {
                "silence_detected": False,
                "speech_detected": False,
                "waiting_for_speech": True,
                "buffer_size": 0
            }

        try:
            # Use the provided function to extract audio bytes
            audio_bytes = extract_audio_data_func(audio_data, conversation_id, self.logger)

            # Ensure we have valid audio bytes before proceeding
            if audio_bytes is None:
                self.logger.error(f"Failed to extract audio data for conversation {conversation_id}")
                return {
                    "silence_detected": False,
                    "speech_detected": False,
                    "waiting_for_speech": True,
                    "buffer_size": 0
                }

            # Get the audio buffer for this conversation
            audio_buffer = self.audio_buffers[conversation_id]
            
            # Add audio data to the buffer and get status
            buffer_status = audio_buffer.add_audio_data(audio_bytes, encoding="ulaw")
            
            self.logger.debug(
                f"Added {len(audio_bytes)} bytes to buffer for conversation {conversation_id}, "
                f"current buffer size: {buffer_status['buffer_size']} bytes, "
                f"silence detected: {buffer_status['silence_detected']}, "
                f"speech detected: {buffer_status['speech_detected']}"
            )
            
            # Return the full buffer status for more detailed information
            return buffer_status
            
        except Exception as e:
            self.logger.error(
                f"Error buffering audio for conversation {conversation_id}: {e}"
            )
            # Don't raise the exception, continue without buffering
            return {
                "silence_detected": False,
                "speech_detected": False,
                "waiting_for_speech": True,
                "buffer_size": 0
            }

    def get_buffered_audio(self, conversation_id: str) -> Optional[bytes]:
        """
        Get buffered audio for a conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            Buffered audio data or None if not available
        """
        if conversation_id not in self.audio_buffers:
            return None
            
        audio_buffer = self.audio_buffers[conversation_id]
        return audio_buffer.get_buffered_audio()

    def reset_audio_buffer(self, conversation_id: str) -> None:
        """
        Reset the audio buffer for a conversation.

        Args:
            conversation_id: Conversation identifier
        """
        if conversation_id in self.audio_buffers:
            self.audio_buffers[conversation_id].reset_buffer()

    def stop_audio_buffering(self, conversation_id: str) -> None:
        """
        Stop audio buffering for a conversation.

        Args:
            conversation_id: Conversation identifier
        """
        if conversation_id in self.audio_buffers:
            try:
                self.audio_buffers[conversation_id].stop_buffering()
                self.logger.debug(f"Stopped audio buffering for conversation {conversation_id}")
            except Exception as e:
                self.logger.error(f"Error stopping audio buffering for conversation {conversation_id}: {e}")

    def cleanup_audio_buffer(self, conversation_id: str) -> None:
        """
        Clean up audio buffer for a conversation.

        Args:
            conversation_id: Conversation identifier
        """
        if conversation_id in self.audio_buffers:
            try:
                self.stop_audio_buffering(conversation_id)
                del self.audio_buffers[conversation_id]
                self.logger.debug(f"Cleaned up audio buffer for conversation {conversation_id}")
            except Exception as e:
                self.logger.error(f"Error cleaning up audio buffer for conversation {conversation_id}: {e}")

    def convert_wxcc_audio_to_lex_format(self, audio_data: bytes) -> bytes:
        """
        Convert WxCC audio format to AWS Lex format.

        Args:
            audio_data: WxCC u-law audio data

        Returns:
            Converted 16-bit PCM audio data at 16kHz
        """
        return convert_wxcc_audio_to_lex_format(audio_data)

    def convert_lex_audio_to_wxcc_format(self, audio_data: bytes) -> tuple[bytes, str]:
        """
        Convert AWS Lex audio format to WxCC format.

        Args:
            audio_data: AWS Lex 16-bit PCM audio data

        Returns:
            Tuple of (WAV audio data, content type)
        """
        return convert_aws_lex_audio_to_wxcc(
            audio_data,
            bit_depth=16  # Lex returns 16-bit PCM
        )

    def log_wxcc_audio(self, conversation_id: str, audio_data: bytes) -> Optional[str]:
        """
        Log incoming WxCC audio if audio logging is enabled.

        Args:
            conversation_id: Conversation identifier
            audio_data: Raw audio data

        Returns:
            Path to the logged file, or None if logging failed or disabled
        """
        if not hasattr(self, 'audio_logging_config') or not self.audio_logging_config.get('enabled', False):
            return None
            
        if not self.audio_logging_config.get('log_all_audio', True):
            return None
            
        if not hasattr(self, 'audio_logger') or not self.audio_logger:
            return None

        try:
            return self.audio_logger.log_audio(
                conversation_id=conversation_id,
                audio_data=audio_data,
                source='wxcc',
                encoding='ulaw'
            )
        except Exception as e:
            self.logger.error(f"Failed to log WxCC audio for conversation {conversation_id}: {e}")
            return None

    def log_aws_audio(self, conversation_id: str, audio_data: bytes) -> Optional[str]:
        """
        Log outgoing AWS Lex audio if audio logging is enabled.

        Args:
            conversation_id: Conversation identifier
            audio_data: Raw audio data

        Returns:
            Path to the logged file, or None if logging failed or disabled
        """
        if not hasattr(self, 'audio_logging_config') or not self.audio_logging_config.get('enabled', False):
            return None
            
        if not self.audio_logging_config.get('log_all_audio', True):
            return None
            
        if not hasattr(self, 'audio_logger') or not self.audio_logger:
            return None

        try:
            return self.audio_logger.log_audio(
                conversation_id=conversation_id,
                audio_data=audio_data,
                source='aws',
                encoding='pcm',
                sample_rate=16000,  # AWS Lex uses 16kHz
                bit_depth=16,       # AWS Lex uses 16-bit
                channels=1          # Mono
            )
        except Exception as e:
            self.logger.error(f"Failed to log AWS audio for conversation {conversation_id}: {e}")
            return None

    def cleanup_audio_logging(self, conversation_id: str) -> None:
        """
        Clean up audio logging resources for a conversation.

        Args:
            conversation_id: Conversation identifier
        """
        if hasattr(self, 'audio_logger') and self.audio_logger:
            try:
                self.audio_logger.cleanup(conversation_id)
            except Exception as e:
                self.logger.error(f"Error cleaning up audio logging for conversation {conversation_id}: {e}")

    def has_audio_buffer(self, conversation_id: str) -> bool:
        """
        Check if an audio buffer exists for a conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            True if buffer exists, False otherwise
        """
        return conversation_id in self.audio_buffers

    def get_audio_buffer_info(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about the audio buffer for a conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            Buffer information dictionary or None if not found
        """
        if conversation_id not in self.audio_buffers:
            return None
            
        audio_buffer = self.audio_buffers[conversation_id]
        return {
            'buffer_size': audio_buffer.get_buffer_size(),
            'is_buffering': audio_buffer.is_buffering(),
            'silence_detected': audio_buffer.get_silence_status()
        }
