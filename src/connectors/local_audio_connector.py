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
        Start a virtual agent session.

        Args:
            session_id: Unique identifier for the session
            request_data: Initial request data

        Returns:
            Dictionary containing welcome message and audio file
        """
        self.logger.info(f"Starting session {session_id}")

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
        }

    def send_message(
        self, session_id: str, message_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send a message to the virtual agent and get response.

        Args:
            session_id: Unique identifier for the session
            message_data: Message data containing text or audio input

        Returns:
            Dictionary containing response message and audio file
        """
        self.logger.info(f"Processing message for session {session_id}")

        # Log relevant parts of message_data without audio bytes
        log_data = {
            "conversation_id": message_data.get("conversation_id"),
            "customer_org_id": message_data.get("customer_org_id"),
            "virtual_agent_id": message_data.get("virtual_agent_id"),
            "input_type": message_data.get("input_type"),
            "text": message_data.get("text", ""),
            "has_audio_data": "audio_data" in message_data,
        }
        self.logger.debug(f"Message data for session {session_id}: {log_data}")

        # Extract text from message data (could be from speech-to-text)
        text = message_data.get("text", "").lower()

        # Check if this is actual speech content or just silence/background noise
        # If there's no text content and it's just audio data, don't respond
        if not text and "audio_data" in message_data:
            audio_data = message_data.get("audio_data", {})
            caller_audio = audio_data.get("caller_audio", b"")

            # Check if the audio is mostly silence (all 0x7f bytes or similar)
            if caller_audio and all(
                b == 0x7F for b in caller_audio[:100]
            ):  # Check first 100 bytes
                self.logger.debug(
                    f"Detected silence/background noise for session {session_id}, not responding"
                )
                return {
                    "audio_content": b"",  # No audio response
                    "text": "",  # No text response
                    "session_id": session_id,
                    "agent_id": self.agent_id,
                    "message_type": "silence",
                }

        # Determine response based on input
        if "transfer" in text or "agent" in text:
            audio_file = self.audio_files.get("transfer", "transferring.wav")
            response_text = "Transferring you to an agent."
            message_type = "transfer"
        elif "error" in text or "problem" in text:
            audio_file = self.audio_files.get("error", "error.wav")
            response_text = "I'm sorry, I encountered an error. Please try again."
            message_type = "error"
        elif "goodbye" in text or "bye" in text or "end" in text:
            audio_file = self.audio_files.get("goodbye", "goodbye.wav")
            response_text = "Thank you for calling, have a great day."
            message_type = "goodbye"
        else:
            # For the default case, use the default audio file (default_response.wav)
            # with the specific text message requested
            audio_file = self.audio_files.get("default", "default_response.wav")
            response_text = "I understand, let me help you with that."
            message_type = "default"

        audio_path = self.audio_base_path / audio_file

        # Read the audio file as bytes
        try:
            with open(audio_path, "rb") as f:
                audio_bytes = f.read()
        except FileNotFoundError:
            self.logger.error(f"Audio file not found: {audio_path}")
            audio_bytes = b""

        self.logger.info(f"Session {session_id} response: {response_text}")

        return {
            "audio_content": audio_bytes,
            "text": response_text,
            "session_id": session_id,
            "agent_id": self.agent_id,
            "message_type": message_type,
        }

    def end_session(self, session_id: str) -> None:
        """
        End a virtual agent session.

        Args:
            session_id: Unique identifier for the session to end
        """
        self.logger.info(f"Ending session {session_id}")

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
