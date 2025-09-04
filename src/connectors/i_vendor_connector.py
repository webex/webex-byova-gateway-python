"""
Abstract base class for vendor connector implementations.

This module defines the interface that all vendor connectors must implement
to integrate with the Webex Contact Center BYOVA Gateway.
"""

import base64
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union, Iterator

# Common event type constants for WxCC integration
class EventTypes:
    """Standard event types for WxCC integration."""
    START_OF_INPUT = "START_OF_INPUT"
    END_OF_INPUT = "END_OF_INPUT"
    SESSION_START = "SESSION_START"
    SESSION_END = "SESSION_END"
    TRANSFER_TO_HUMAN = "TRANSFER_TO_HUMAN"
    CONVERSATION_END = "CONVERSATION_END"
    CUSTOM_EVENT = "CUSTOM_EVENT"
    NO_INPUT = "NO_INPUT"
    NO_MATCH = "NO_MATCH"

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
    ) -> Iterator[Optional[Dict[str, Any]]]:
        """
        Send a message or audio to the virtual agent.

        Args:
            conversation_id: Unique identifier for the conversation
            message_data: Message data including audio bytes, text, or events

        Returns:
            Iterator yielding response dictionaries from the virtual agent.
            Yield None when no response is needed.
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
        # Default implementation: return the bytes unchanged
        return audio_bytes, detected_encoding

    def create_output_event(self, event_type: str, name: str = "", event_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Create a standardized output event for WxCC integration.
        
        Args:
            event_type: Type of event (use EventTypes constants)
            name: Name/identifier for the event
            event_data: Optional additional event data
            
        Returns:
            Standardized output event dictionary
        """
        event = {
            "event_type": event_type,
            "name": name,
            "metadata": event_data if event_data else None
        }
        
        return event
    
    def create_response(self, conversation_id: str, message_type: str = "silence",
                       text: str = "", audio_content: bytes = b"",
                       barge_in_enabled: bool = False, output_events: Optional[List[Dict[str, Any]]] = None,
                       **additional_params) -> Dict[str, Any]:
        """
        Create a standardized response dictionary with common fields.

        Args:
            conversation_id: Unique identifier for the conversation
            message_type: Type of message (silence, welcome, transfer, etc.)
            text: Text response to send to the client
            audio_content: Audio bytes to send to the client
            barge_in_enabled: Whether barge-in is enabled for this response
            output_events: List of output events to include
            **additional_params: Additional parameters to include in the response

        Returns:
            Standardized response dictionary with common fields
        """
        # Create base response
        response = {
            "audio_content": audio_content,
            "text": text,
            "conversation_id": conversation_id,
            "agent_id": getattr(self, "agent_id", "Unknown"),  # Use agent_id if available
            "message_type": message_type,
            "barge_in_enabled": barge_in_enabled
        }

        # Initialize output_events if provided
        if output_events:
            response["output_events"] = output_events
        else:
            response["output_events"] = []

        # Add any additional parameters
        response.update(additional_params)

        return response

    def create_transfer_response(self, conversation_id: str, text: str = "", 
                                audio_content: bytes = b"", reason: str = "user_requested_transfer") -> Dict[str, Any]:
        """
        Create a transfer response with TRANSFER_TO_HUMAN event.
        
        Args:
            conversation_id: Unique identifier for the conversation
            text: Transfer message text
            audio_content: Optional audio content
            reason: Reason for transfer
            
        Returns:
            Response with transfer event
        """
        transfer_event = self.create_output_event(
            EventTypes.TRANSFER_TO_HUMAN,
            "transfer_requested",
            {"reason": reason, "conversation_id": conversation_id}
        )
        
        return self.create_response(
            conversation_id=conversation_id,
            message_type="transfer",
            text=text,
            audio_content=audio_content,
            barge_in_enabled=False,
            response_type="final",
            output_events=[transfer_event]
        )
    
    def create_goodbye_response(self, conversation_id: str, text: str = "", 
                               audio_content: bytes = b"", reason: str = "user_requested_end") -> Dict[str, Any]:
        """
        Create a goodbye response with CONVERSATION_END event.
        
        Args:
            conversation_id: Unique identifier for the conversation
            text: Goodbye message text
            audio_content: Optional audio content
            reason: Reason for ending conversation
            
        Returns:
            Response with conversation end event
        """
        end_event = self.create_output_event(
            EventTypes.CONVERSATION_END,
            "conversation_ended",
            {"reason": reason, "conversation_id": conversation_id}
        )
        
        return self.create_response(
            conversation_id=conversation_id,
            message_type="goodbye",
            text=text,
            audio_content=audio_content,
            barge_in_enabled=False,
            response_type="final",
            output_events=[end_event]
        )
    
    def create_session_start_response(self, conversation_id: str, text: str = "", 
                                    audio_content: bytes = b"") -> Dict[str, Any]:
        """
        Create a session start response with SESSION_START event.
        
        Args:
            conversation_id: Unique identifier for the conversation
            text: Welcome message text
            audio_content: Optional audio content
            
        Returns:
            Response with session start event
        """
        start_event = self.create_output_event(
            EventTypes.SESSION_START,
            "session_started",
            {"conversation_id": conversation_id}
        )
        
        return self.create_response(
            conversation_id=conversation_id,
            message_type="welcome",
            text=text,
            audio_content=audio_content,
            barge_in_enabled=True,
            response_type="silence",
            output_events=[start_event]
        )
    
    def create_start_of_input_response(self, conversation_id: str, text: str = "", 
                                      audio_content: bytes = b"") -> Dict[str, Any]:
        """
        Create a start of input response with START_OF_INPUT event.
        
        Args:
            conversation_id: Unique identifier for the conversation
            text: Optional text (usually empty for start of input)
            audio_content: Optional audio content
            
        Returns:
            Response with start of input event
        """
        start_event = self.create_output_event(
            EventTypes.START_OF_INPUT,
            ""  # Empty name for START_OF_INPUT event
        )
        
        return self.create_response(
            conversation_id=conversation_id,
            message_type="silence",
            text=text,
            audio_content=audio_content,
            barge_in_enabled=True,
            response_type="silence",
            output_events=[start_event]
        )

    def create_end_of_input_response(self, conversation_id: str, text: str = "", 
                                    audio_content: bytes = b"") -> Dict[str, Any]:
        """
        Create an end of input response with END_OF_INPUT event.
        
        Args:
            conversation_id: Unique identifier for the conversation
            text: Optional text (usually empty for end of input)
            audio_content: Optional audio content
            
        Returns:
            Response with end of input event
        """
        end_event = self.create_output_event(
            EventTypes.END_OF_INPUT,
            "end_of_input"
        )
        
        return self.create_response(
            conversation_id=conversation_id,
            message_type="silence",
            text=text,
            audio_content=audio_content,
            barge_in_enabled=True,
            response_type="silence",
            output_events=[end_event]
        )

    def handle_conversation_start(self, conversation_id: str, message_data: Dict[str, Any],
                                logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
        """
        Handle conversation start events.

        Args:
            conversation_id: Unique identifier for the conversation
            message_data: Message data containing the conversation start event
            logger: Optional logger instance

        Returns:
            Standardized silence response
        """
        if logger:
            logger.info(f"Ignoring conversation start event in send_message for conversation {conversation_id}")

        return self.create_response(
            conversation_id=conversation_id,
            message_type="silence"
        )

    def handle_event(self, conversation_id: str, message_data: Dict[str, Any],
                    logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
        """
        Handle event inputs.

        Args:
            conversation_id: Unique identifier for the conversation
            message_data: Message data containing the event
            logger: Optional logger instance

        Returns:
            Standardized silence response
        """
        if logger and "event_data" in message_data:
            event_name = message_data.get("event_data", {}).get("name", "")
            logger.info(f"Event for conversation {conversation_id}: {event_name}")

        return self.create_response(
            conversation_id=conversation_id,
            message_type="silence"
        )

    def handle_audio_input(self, conversation_id: str, message_data: Dict[str, Any],
                          logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
        """
        Handle audio input by returning a silence response.
        Subclasses may override this to process the audio input.

        Args:
            conversation_id: Unique identifier for the conversation
            message_data: Message data containing audio input
            logger: Optional logger instance

        Returns:
            Standardized silence response
        """
        if logger:
            logger.debug(f"Received audio input for conversation {conversation_id}")

        return self.create_response(
            conversation_id=conversation_id,
            message_type="silence"
        )

    def handle_unrecognized_input(self, conversation_id: str, message_data: Dict[str, Any],
                                 logger: Optional[logging.Logger] = None) -> Dict[str, Any]:
        """
        Handle unrecognized input types by returning a silence response.

        Args:
            conversation_id: Unique identifier for the conversation
            message_data: Message data with unrecognized input type
            logger: Optional logger instance

        Returns:
            Standardized silence response
        """
        if logger:
            logger.debug(
                f"Unhandled input type for conversation {conversation_id}: {message_data.get('input_type')}"
            )

        return self.create_response(
            conversation_id=conversation_id,
            message_type="silence"
        )

    def check_silence_timeout(self, conversation_id: str, record_caller_audio: bool = False,
                            audio_recorders: Optional[Dict[str, Any]] = None,
                            logger: Optional[logging.Logger] = None) -> None:
        """
        Check for silence timeout in audio recordings.

        Args:
            conversation_id: Unique identifier for the conversation
            record_caller_audio: Whether caller audio recording is enabled
            audio_recorders: Dictionary of audio recorders by conversation ID
            logger: Optional logger instance
        """
        if not record_caller_audio or not audio_recorders or conversation_id not in audio_recorders:
            return

        if hasattr(audio_recorders[conversation_id], "check_silence_timeout"):
            if not audio_recorders[conversation_id].check_silence_timeout():
                if logger:
                    logger.info(f"Recording finalized due to silence timeout for conversation {conversation_id}")
