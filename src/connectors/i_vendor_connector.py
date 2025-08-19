"""
Abstract base class for vendor connector implementations.

This module defines the interface that all vendor connectors must implement
to integrate with the Webex Contact Center BYOVA Gateway.
"""

import base64
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class IVendorConnector(ABC):
    """
    Abstract base class for vendor connector implementations.

    All vendor connectors must inherit from this class and implement
    the required abstract methods to provide a unified interface
    for virtual agent communication.
    """

    @abstractmethod
    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialize the connector with configuration data.

        Args:
            config: Configuration dictionary containing vendor-specific settings
                   such as API endpoints, authentication credentials, etc.
        """
        pass

    @abstractmethod
    def start_conversation(
        self, conversation_id: str, request_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Start a virtual agent conversation.

        Args:
            conversation_id: Unique identifier for the conversation
            request_data: Initial request data including agent ID, user info, etc.

        Returns:
            Dictionary containing conversation initialization response from the vendor
        """
        pass

    @abstractmethod
    def send_message(
        self, conversation_id: str, message_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send a message or audio to the virtual agent.

        Args:
            conversation_id: Unique identifier for the conversation
            message_data: Message data including audio bytes, text, or events

        Returns:
            Dictionary containing the virtual agent's response
        """
        pass

    @abstractmethod
    def end_conversation(self, conversation_id: str, message_data: Dict[str, Any] = None) -> None:
        """
        End a virtual agent conversation.

        Args:
            conversation_id: Unique identifier for the conversation to end
            message_data: Optional message data for the conversation end (default: None)
        """
        pass

    @abstractmethod
    def get_available_agents(self) -> List[str]:
        """
        Get a list of available virtual agent IDs.

        Returns:
            List of virtual agent ID strings that this connector can provide
        """
        pass

    @abstractmethod
    def convert_wxcc_to_vendor(self, grpc_data: Any) -> Any:
        """
        Convert data from WxCC gRPC format to vendor's native format.

        Args:
            grpc_data: Data in WxCC gRPC format (e.g., VoiceVARequest)

        Returns:
            Data converted to vendor's native format
        """
        pass

    @abstractmethod
    def convert_vendor_to_wxcc(self, vendor_data: Any) -> Any:
        """
        Convert data from vendor's native format to WxCC gRPC format.

        Args:
            vendor_data: Data in vendor's native format

        Returns:
            Data converted to WxCC gRPC format (e.g., VoiceVAResponse)
        """
        pass

    def extract_audio_data(self, audio_data: Any, conversation_id: str, logger: Optional[logging.Logger] = None) -> Optional[bytes]:
        """
        Extract audio bytes from different formats of audio data.

        Args:
            audio_data: Audio data in various formats (dict, str, bytes, bytearray)
            conversation_id: Unique identifier for the conversation
            logger: Optional logger instance for logging

        Returns:
            Extracted audio bytes or None if extraction fails
        """
        if not audio_data:
            if logger:
                logger.error(f"No audio data provided for conversation {conversation_id}")
            return None

        # Initialize audio_bytes variable
        audio_bytes = None

        if logger:
            logger.debug(f"Processing audio data of type {type(audio_data)} for {conversation_id}")

        # Ensure audio_data is bytes - handle various input types
        if isinstance(audio_data, dict):
            # Extract audio data from dictionary
            if logger:
                logger.debug(f"Audio data is dictionary with keys: {list(audio_data.keys())}")

            audio_bytes = self._extract_from_dict(audio_data, conversation_id, logger)
        elif isinstance(audio_data, str):
            if logger:
                logger.debug(f"Audio data is string type, length: {len(audio_data)}")

            # If string is empty, log error and return
            if not audio_data:
                if logger:
                    logger.error(f"Empty string audio data received for {conversation_id}")
                return None

            audio_bytes = self._extract_from_string(audio_data, conversation_id, logger)
        elif isinstance(audio_data, (bytes, bytearray)):
            if logger:
                logger.debug(f"Audio data is already in bytes type, length: {len(audio_data)}")

            # If bytes are empty, log error and return
            if not audio_data:
                if logger:
                    logger.error(f"Empty bytes audio data received for {conversation_id}")
                return None

            # Only log data in debug mode
            if logger and logger.isEnabledFor(logging.DEBUG):
                # Convert bytes to hex for better visibility in logs
                hex_preview = audio_data[:50].hex()
                logger.debug(
                    f"Processing bytes audio data for {conversation_id}, hex preview: {hex_preview}..."
                )
            elif logger:
                logger.debug(
                    f"Processing bytes audio data for {conversation_id} (length: {len(audio_data)})"
                )
            audio_bytes = audio_data
        else:
            if logger:
                logger.error(
                    f"Unsupported audio data type: {type(audio_data)} for {conversation_id}"
                )
            return None

        return audio_bytes

    def _extract_from_dict(self, audio_dict: Dict[str, Any], conversation_id: str,
                          logger: Optional[logging.Logger] = None) -> Optional[bytes]:
        """
        Extract audio bytes from a dictionary.

        Args:
            audio_dict: Dictionary potentially containing audio data
            conversation_id: Unique identifier for the conversation
            logger: Optional logger instance for logging

        Returns:
            Extracted audio bytes or None if extraction fails
        """
        if "audio_data" in audio_dict:
            if logger:
                logger.debug(
                    f"Extracting audio data from dictionary key 'audio_data' for {conversation_id}"
                )
            audio_data = audio_dict["audio_data"]
            if logger:
                logger.debug(f"Extracted audio data type: {type(audio_data)}")
            return audio_data
        else:
            # Try to find any key that might contain audio data
            audio_keys = [k for k in audio_dict.keys() if "audio" in k.lower()]
            if audio_keys:
                key = audio_keys[0]
                if logger:
                    logger.debug(
                        f"Found audio data under key '{key}' for {conversation_id}"
                    )
                audio_data = audio_dict[key]
                if logger:
                    logger.debug(f"Extracted audio data type: {type(audio_data)}")
                return audio_data
            else:
                if logger:
                    logger.error(
                        f"No audio data found in dictionary for {conversation_id}. Keys: {list(audio_dict.keys())}"
                    )
                return None

    def _extract_from_string(self, audio_str: str, conversation_id: str,
                            logger: Optional[logging.Logger] = None) -> Optional[bytes]:
        """
        Extract audio bytes from a string (potentially base64-encoded).

        Args:
            audio_str: String potentially containing audio data
            conversation_id: Unique identifier for the conversation
            logger: Optional logger instance for logging

        Returns:
            Extracted audio bytes or None if extraction fails
        """
        # Only log full audio data in debug mode
        if logger and logger.isEnabledFor(logging.DEBUG):
            # Log the first few characters to understand the format
            first_chars = audio_str[:100].replace('\n', '\\n').replace('\r', '\\r')
            logger.debug(
                f"Converting string audio data to bytes for {conversation_id}, data preview: '{first_chars}...'"
            )
        elif logger:
            logger.debug(
                f"Converting string audio data to bytes for {conversation_id} (length: {len(audio_str)})"
            )

        # Try to convert from base64 string
        try:
            # Try to decode as base64 first
            if logger:
                logger.debug(f"Attempting base64 decode for {conversation_id}")
            audio_bytes = base64.b64decode(audio_str)
            if logger:
                logger.debug(f"Base64 decode successful, got {len(audio_bytes)} bytes")
            return audio_bytes
        except Exception as e:
            if logger:
                logger.debug(f"Base64 decode failed: {e}, trying direct encoding")
            # If not base64, try direct encoding
            try:
                audio_bytes = audio_str.encode("latin1")  # Use latin1 to preserve byte values
                if logger:
                    logger.debug(f"Direct encoding successful, got {len(audio_bytes)} bytes")
                return audio_bytes
            except Exception as encode_error:
                if logger:
                    logger.error(f"Failed to encode string as bytes: {encode_error}")
                return None

    def process_audio_format(self, audio_bytes: bytes, detected_encoding: str,
                            conversation_id: str) -> Tuple[bytes, str]:
        """
        Process audio format to ensure compatibility with the system.

        This is a placeholder method that subclasses may override to provide specific
        audio format processing. The base implementation returns the audio bytes unchanged.

        Args:
            audio_bytes: Raw audio data as bytes
            detected_encoding: Detected encoding string (e.g., "ulaw", "pcm_16bit")
            conversation_id: Unique identifier for the conversation

        Returns:
            Tuple of (processed_audio_bytes, resulting_encoding)
        """
        # Base implementation just returns the audio data unchanged
        # Subclasses can override to provide format conversion
        return audio_bytes, detected_encoding
