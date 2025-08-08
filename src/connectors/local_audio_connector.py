"""
Local Audio Connector implementation.

This connector simulates a virtual agent by playing local audio files.
It's useful for testing and development purposes.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

from .i_vendor_connector import IVendorConnector


class LocalAudioConnector(IVendorConnector):
    """
    Local audio connector for testing and development.

    This connector simulates a virtual agent by playing local audio files
    from the audio directory. It's useful for testing the gateway without
    requiring an actual vendor integration.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialize the local audio connector.

        Args:
            config: Configuration dictionary containing:
                   - 'audio_base_path': Base path to audio directory (optional)
                   - 'agent_id': Custom agent ID (optional, defaults to "Local Playback")
        """
        self.agent_id = config.get("agent_id", "Local Playback")
        self.audio_base_path = Path(config.get("audio_base_path", "audio"))

        # Ensure audio directory exists
        self.audio_base_path.mkdir(exist_ok=True)

        # Set up logging
        self.logger = logging.getLogger(__name__)

        # Audio file mappings for different scenarios
        self.audio_files = config.get(
            "audio_files",
            {
                "welcome": "welcome.wav",
                "transfer": "transferring.wav",
                "goodbye": "goodbye.wav",
                "error": "error.wav",
                "default": "default_response.wav",
            },
        )

        self.logger.info(
            f"LocalAudioConnector initialized with audio path: {self.audio_base_path}"
        )

    def get_available_agents(self) -> List[str]:
        """
        Get available virtual agent IDs.

        Returns:
            List containing the local playback agent ID
        """
        return [self.agent_id]

    def start_session(
        self, session_id: str, request_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Start a virtual agent conversation.

        Note: This method uses 'session' terminology for vendor compatibility,
        but it actually manages conversations (calls into WxCC).

        Args:
            session_id: Unique identifier for the conversation (maps to conversation_id)
            request_data: Initial request data

        Returns:
            Dictionary containing welcome message and audio file
        """
        self.logger.info(f"Starting conversation {session_id}")

        # Get welcome audio file
        welcome_audio = self.audio_files.get("welcome", "welcome.wav")
        audio_path = self.audio_base_path / welcome_audio

        # Read the audio file as bytes
        try:
            with open(audio_path, "rb") as f:
                audio_bytes = f.read()
        except FileNotFoundError:
            self.logger.error(f"Audio file not found: {audio_path}")
            audio_bytes = b""

        return {
            "audio_content": audio_bytes,
            "text": "Hello, welcome to the webex contact center voice virtual agent gateway. How can I help you today?",
            "session_id": session_id,
            "agent_id": self.agent_id,
            "message_type": "welcome",
            "barge_in_enabled": False,  # Disable barge-in for welcome message
        }

    def send_message(
        self, session_id: str, message_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send a message to the virtual agent and get response.

        Note: This method uses 'session' terminology for vendor compatibility,
        but it actually manages conversations (calls into WxCC).

        Args:
            session_id: Unique identifier for the conversation (maps to conversation_id)
            message_data: Message data containing text or audio input

        Returns:
            Dictionary containing response message and audio file
        """
        self.logger.info(f"Processing message for conversation {session_id}")

        # Log relevant parts of message_data without audio bytes
        log_data = {
            "conversation_id": message_data.get("conversation_id"),
            "virtual_agent_id": message_data.get("virtual_agent_id"),
            "input_type": message_data.get("input_type"),
        }
        self.logger.debug(f"Message data for conversation {session_id}: {log_data}")

        # Ignore session start events - these should be handled by start_session method
        if message_data.get("input_type") == "session_start":
            self.logger.info(f"Ignoring session start event in send_message for conversation {session_id}")
            return {
                "audio_content": b"",
                "text": "",
                "session_id": session_id,
                "agent_id": self.agent_id,
                "message_type": "silence",
                "barge_in_enabled": False,
            }

        # Handle DTMF input - check for transfer and log the digits
        if message_data.get("input_type") == "dtmf" and "dtmf_data" in message_data:
            dtmf_data = message_data.get("dtmf_data", {})
            dtmf_events = dtmf_data.get("dtmf_events", [])
            if dtmf_events:
                self.logger.info(f"Received DTMF input for conversation {session_id}: {dtmf_events}")
                # Convert DTMF events to a string for easier processing
                dtmf_string = "".join([str(digit) for digit in dtmf_events])
                self.logger.info(f"DTMF digits entered: {dtmf_string}")
                
                # Check if user entered '5' for transfer
                if len(dtmf_events) == 1 and dtmf_events[0] == 5:  # DTMF_DIGIT_FIVE = 5
                    self.logger.info(f"Transfer requested by user for conversation {session_id}")
                    
                    # Get transfer audio file
                    transfer_audio = self.audio_files.get("transfer", "transferring.wav")
                    audio_path = self.audio_base_path / transfer_audio
                    
                    # Read the audio file as bytes
                    try:
                        with open(audio_path, "rb") as f:
                            audio_bytes = f.read()
                    except FileNotFoundError:
                        self.logger.error(f"Transfer audio file not found: {audio_path}")
                        audio_bytes = b""
                    
                    # Return transfer response
                    return {
                        "audio_content": audio_bytes,
                        "text": "Transferring you to an agent. Please wait.",
                        "session_id": session_id,
                        "agent_id": self.agent_id,
                        "message_type": "transfer",
                        "barge_in_enabled": False,
                    }
                
                # Check if user entered '6' for goodbye
                elif len(dtmf_events) == 1 and dtmf_events[0] == 6:  # DTMF_DIGIT_SIX = 6
                    self.logger.info(f"Goodbye requested by user for conversation {session_id}")
                    
                    # Get goodbye audio file
                    goodbye_audio = self.audio_files.get("goodbye", "goodbye.wav")
                    audio_path = self.audio_base_path / goodbye_audio
                    
                    # Read the audio file as bytes
                    try:
                        with open(audio_path, "rb") as f:
                            audio_bytes = f.read()
                    except FileNotFoundError:
                        self.logger.error(f"Goodbye audio file not found: {audio_path}")
                        audio_bytes = b""
                    
                    # Return goodbye response
                    return {
                        "audio_content": audio_bytes,
                        "text": "Thank you for calling. Goodbye!",
                        "session_id": session_id,
                        "agent_id": self.agent_id,
                        "message_type": "goodbye",
                        "barge_in_enabled": False,
                    }
            
            # Return silence response for other DTMF inputs (no audio response)
            return {
                "audio_content": b"",
                "text": "",
                "session_id": session_id,
                "agent_id": self.agent_id,
                "message_type": "silence",
                "barge_in_enabled": False,
            }

        # Handle event inputs - log start and end of input events
        if message_data.get("input_type") == "event" and "event_data" in message_data:
            event_data = message_data.get("event_data", {})
            event_name = event_data.get("name", "")
            
            self.logger.info(f"Event for conversation {session_id}: {event_name}")
            
            # Return silence response for events (no audio response)
            return {
                "audio_content": b"",
                "text": "",
                "session_id": session_id,
                "agent_id": self.agent_id,
                "message_type": "silence",
                "barge_in_enabled": False,
            }

        # Handle audio input - return silence (no processing)
        if message_data.get("input_type") == "audio":
            self.logger.debug(f"Received audio input for conversation {session_id}")
            return {
                "audio_content": b"",
                "text": "",
                "session_id": session_id,
                "agent_id": self.agent_id,
                "message_type": "silence",
                "barge_in_enabled": False,
            }

        # Default: return silence for any other input type
        self.logger.debug(f"Unhandled input type for conversation {session_id}: {message_data.get('input_type')}")
        return {
            "audio_content": b"",
            "text": "",
            "session_id": session_id,
            "agent_id": self.agent_id,
            "message_type": "silence",
            "barge_in_enabled": False,
        }

    def end_session(self, session_id: str) -> None:
        """
        End a virtual agent conversation.

        Note: This method uses 'session' terminology for vendor compatibility,
        but it actually manages conversations (calls into WxCC).

        Args:
            session_id: Unique identifier for the conversation to end (maps to conversation_id)
        """
        self.logger.info(f"Ending conversation {session_id}")

        # Simulate playing goodbye message
        goodbye_audio = self.audio_files.get("goodbye", "goodbye.wav")
        audio_path = self.audio_base_path / goodbye_audio

        self.logger.info(f"Playing goodbye message: {audio_path}")

    def convert_wxcc_to_vendor(self, grpc_data: Any) -> Any:
        """
        Convert WxCC gRPC data to vendor format.

        For the local connector, we extract relevant information from the gRPC data
        to use in our send_message method.

        Args:
            grpc_data: Data in WxCC gRPC format

        Returns:
            Simplified dictionary with relevant data for local processing
        """
        # Extract relevant data from gRPC format
        if hasattr(grpc_data, "voice_va_input_type"):
            # Handle voice input
            if hasattr(grpc_data, "audio_input"):
                return {
                    "type": "audio",
                    "audio_data": grpc_data.audio_input.caller_audio,
                    "encoding": grpc_data.audio_input.encoding,
                    "sample_rate": grpc_data.audio_input.sample_rate_hertz,
                    "language_code": grpc_data.audio_input.language_code,
                }
            elif hasattr(grpc_data, "dtmf_input"):
                return {"type": "dtmf", "dtmf_digits": grpc_data.dtmf_input.dtmf_digits}
            elif hasattr(grpc_data, "event_input"):
                return {"type": "event", "event_type": grpc_data.event_input.event_type}

        # For simplicity, return as-is if we can't parse it
        return grpc_data

    def convert_vendor_to_wxcc(self, vendor_data: Any) -> Any:
        """
        Convert vendor data to WxCC gRPC format.

        Converts the dictionary returned by start_session/send_message
        into a format that can be used to construct WxCC gRPC responses.

        Args:
            vendor_data: Data in vendor's native format (dict from local connector)

        Returns:
            Dictionary that can be used to construct WxCC gRPC responses
        """
        if not isinstance(vendor_data, dict):
            return vendor_data

        # Convert local connector response to WxCC format
        response = {
            "text": vendor_data.get("text", ""),
            "audio_file": vendor_data.get("audio_file", ""),
            "session_id": vendor_data.get("session_id", ""),
            "agent_id": vendor_data.get("agent_id", ""),
            "message_type": vendor_data.get("message_type", "default"),
            "input_sensitive": False,
            "input_mode": "VOICE",  # Default to voice input
            "output_events": [],
            "prompts": [],
        }

        # Add prompt information if text is available
        if response["text"]:
            response["prompts"].append(
                {
                    "text": response["text"],
                    "ssml": f"<speak>{response['text']}</speak>",
                    "language_code": "en-US",
                }
            )

        # Add output events based on message type
        if response["message_type"] == "goodbye":
            response["output_events"].append(
                {
                    "event_type": "SESSION_END",
                    "event_data": {
                        "reason": "user_requested_end",
                        "session_id": response["session_id"],
                    },
                }
            )
        elif response["message_type"] == "transfer":
            response["output_events"].append(
                {
                    "event_type": "TRANSFER_TO_HUMAN",
                    "event_data": {
                        "reason": "user_requested_transfer",
                        "session_id": response["session_id"],
                    },
                }
            )

        return response
