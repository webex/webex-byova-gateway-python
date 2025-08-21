"""
Local Audio Connector implementation.

This connector simulates a virtual agent by playing local audio files.
It's useful for testing and development purposes.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

from ..utils.audio_utils import AudioConverter
from ..utils.audio_buffer import AudioBuffer
from ..utils.audio_recorder import AudioRecorder
from .i_vendor_connector import IVendorConnector, EventTypes


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
                   - 'record_caller_audio': Whether to record caller audio (optional, defaults to False)
                   - 'audio_recording': Dictionary with audio recording configuration:
                     - 'output_dir': Directory to save recorded audio (optional, defaults to "logs")
                     - 'silence_threshold': Amplitude threshold for silence detection (optional)
                     - 'silence_duration': Amount of silence in seconds before stopping recording (optional)
        """
        self.agent_id = config.get("agent_id", "Local Playback")
        self.audio_base_path = Path(config.get("audio_base_path", "audio"))

        # Ensure audio directory exists
        self.audio_base_path.mkdir(exist_ok=True)

        # Set up logging
        self.logger = logging.getLogger(__name__)

        # Initialize audio converter for WXCC compatibility
        self.audio_converter = AudioConverter(self.logger)

        # Audio recording configuration
        self.record_caller_audio = config.get("record_caller_audio", False)
        self.audio_recorders = {}  # Dictionary to store audio recorders by conversation ID

        # Get audio recording configuration
        self.audio_recording_config = config.get("audio_recording", {})

        if self.record_caller_audio:
            self.logger.info("Caller audio recording is enabled")

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
            List containing the local playback agent ID with connector prefix
        """
        return [f"Local Audio: {self.agent_id}"]

    def start_conversation(
        self, conversation_id: str, request_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Start a virtual agent conversation.

        Args:
            conversation_id: Unique identifier for the conversation
            request_data: Initial request data

        Returns:
            Dictionary containing welcome message and audio file
        """
        self.logger.info(f"Starting conversation {conversation_id}")

        # Initialize audio recorder for this conversation if recording is enabled
        if self.record_caller_audio:
            self._init_audio_recorder(conversation_id)

        # Get welcome audio file
        welcome_audio = self.audio_files.get("welcome", "welcome.wav")
        audio_path = self.audio_base_path / welcome_audio

        # Convert audio file to WXCC-compatible format
        try:
            audio_bytes = self._convert_audio_to_wxcc_format(audio_path)
        except Exception as e:
            self.logger.error(f"Error converting welcome audio file {audio_path}: {e}")
            audio_bytes = b""

        return {
            "audio_content": audio_bytes,
            "text": "Hello, welcome to the webex contact center voice virtual agent gateway. How can I help you today?",
            "conversation_id": conversation_id,
            "agent_id": self.agent_id,
            "message_type": "welcome",
            "barge_in_enabled": False,  # Disable barge-in for welcome message
        }

    def send_message(
        self, conversation_id: str, message_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send a message to the virtual agent and get response.

        Args:
            conversation_id: Unique identifier for the conversation
            message_data: Message data containing text or audio input

        Returns:
            Dictionary containing response message and audio file
        """
        self.logger.info(f"Processing message for conversation {conversation_id}")

        # Log relevant parts of message_data without audio bytes
        log_data = {
            "conversation_id": message_data.get("conversation_id"),
            "virtual_agent_id": message_data.get("virtual_agent_id"),
            "input_type": message_data.get("input_type"),
        }
        self.logger.debug(
            f"Message data for conversation {conversation_id}: {log_data}"
        )

        # Ignore conversation start events - these should be handled by start_conversation method
        if message_data.get("input_type") == "conversation_start":
            return self.handle_conversation_start(conversation_id, message_data, self.logger)

        # Handle DTMF input - check for transfer and log the digits
        if message_data.get("input_type") == "dtmf" and "dtmf_data" in message_data:
            dtmf_data = message_data.get("dtmf_data", {})
            dtmf_events = dtmf_data.get("dtmf_events", [])
            if dtmf_events:
                self.logger.info(
                    f"Received DTMF input for conversation {conversation_id}: {dtmf_events}"
                )
                # Convert DTMF events to a string for easier processing
                dtmf_string = "".join([str(digit) for digit in dtmf_events])
                self.logger.info(f"DTMF digits entered: {dtmf_string}")

                # Check if user entered '5' for transfer
                if len(dtmf_events) == 1 and dtmf_events[0] == 5:  # DTMF_DIGIT_FIVE = 5
                    self.logger.info(
                        f"Transfer requested by user for conversation {conversation_id}"
                    )

                    # Get transfer audio file
                    transfer_audio = self.audio_files.get(
                        "transfer", "transferring.wav"
                    )
                    audio_path = self.audio_base_path / transfer_audio

                    # Convert audio file to WXCC-compatible format
                    try:
                        audio_bytes = self._convert_audio_to_wxcc_format(audio_path)
                    except Exception as e:
                        self.logger.error(
                            f"Error converting transfer audio file {audio_path}: {e}"
                        )
                        audio_bytes = b""

                    # Return transfer response
                    return self.create_response(
                        conversation_id=conversation_id,
                        message_type="transfer",
                        text="Transferring you to an agent. Please wait.",
                        audio_content=audio_bytes,
                        barge_in_enabled=False
                    )

                # Check if user entered '6' for goodbye
                elif (
                    len(dtmf_events) == 1 and dtmf_events[0] == 6
                ):  # DTMF_DIGIT_SIX = 6
                    self.logger.info(
                        f"Goodbye requested by user for conversation {conversation_id}"
                    )

                    # Get goodbye audio file
                    goodbye_audio = self.audio_files.get("goodbye", "goodbye.wav")
                    audio_path = self.audio_base_path / goodbye_audio

                    # Convert audio file to WXCC-compatible format
                    try:
                        audio_bytes = self._convert_audio_to_wxcc_format(audio_path)
                    except Exception as e:
                        self.logger.error(
                            f"Error converting goodbye audio file {audio_path}: {e}"
                        )
                        audio_bytes = b""

                    # Return goodbye response
                    return self.create_response(
                        conversation_id=conversation_id,
                        message_type="goodbye",
                        text="Thank you for calling. Goodbye!",
                        audio_content=audio_bytes,
                        barge_in_enabled=False
                    )

            # Check for silence timeout when DTMF inputs are received
            self.check_silence_timeout(
                conversation_id, self.record_caller_audio, self.audio_recorders, self.logger
            )

            # Return silence response for other DTMF inputs (no audio response)
            return self.create_response(
                conversation_id=conversation_id,
                message_type="silence"
            )

        # Handle event inputs - log start and end of input events
        if message_data.get("input_type") == "event" and "event_data" in message_data:
            # Check for silence timeout when events are received
            self.check_silence_timeout(
                conversation_id, self.record_caller_audio, self.audio_recorders, self.logger
            )

            # Return silence response for events (no audio response)
            return self.handle_event(conversation_id, message_data, self.logger)

        # Handle audio input - return silence (no processing)
        if message_data.get("input_type") == "audio":
            # Record audio if enabled
            if self.record_caller_audio and "audio_data" in message_data:
                self._process_audio_for_recording(
                    message_data["audio_data"], conversation_id
                )

            # Check for silence timeout even when audio data is received
            self.check_silence_timeout(
                conversation_id, self.record_caller_audio, self.audio_recorders, self.logger
            )

            return self.handle_audio_input(conversation_id, message_data, self.logger)

        # Default: return silence for any other input type
        # Check for silence timeout for any unhandled input types
        self.check_silence_timeout(
            conversation_id, self.record_caller_audio, self.audio_recorders, self.logger
        )

        return self.handle_unrecognized_input(conversation_id, message_data, self.logger)

    def end_conversation(
        self, conversation_id: str, message_data: Dict[str, Any] = None
    ) -> None:
        """
        End a virtual agent conversation.

        Args:
            conversation_id: Unique identifier for the conversation to end
            message_data: Optional message data for the conversation end (default: None)
        """
        self.logger.info(f"Ending conversation {conversation_id}")

        # Log message data if provided
        if message_data:
            self.logger.debug(f"End conversation message data: {message_data}")

        # Finalize audio recording if enabled
        if self.record_caller_audio and conversation_id in self.audio_recorders:
            file_path = self.audio_recorders[conversation_id].finalize_recording()
            if file_path:
                self.logger.info(f"Audio recording saved to {file_path}")
            else:
                self.logger.info(f"No audio recording was created for conversation {conversation_id} (no speech detected)")
            del self.audio_recorders[conversation_id]

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
                    "input_type": "audio",  # Add input_type for send_message compatibility
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

        Converts the dictionary returned by start_conversation/send_message
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
            "conversation_id": vendor_data.get("conversation_id", ""),
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
                self.create_output_event(
                    EventTypes.CONVERSATION_END,
                    "conversation_ended",
                    {
                        "reason": "user_requested_end",
                        "conversation_id": response["conversation_id"],
                    }
                )
            )
        elif response["message_type"] == "transfer":
            response["output_events"].append(
                self.create_output_event(
                    EventTypes.TRANSFER_TO_HUMAN,
                    "transfer_requested",
                    {
                        "reason": "user_requested_transfer",
                        "conversation_id": response["conversation_id"],
                    }
                )
            )

        return response

    def _init_audio_recorder(self, conversation_id: str) -> None:
        """
        Initialize an audio recorder for a conversation.

        Args:
            conversation_id: Unique identifier for the conversation
        """
        if conversation_id in self.audio_recorders:
            self.logger.info(
                f"Audio recorder already exists for conversation {conversation_id}"
            )
            return

        try:
            # Get audio recording configuration
            output_dir = self.audio_recording_config.get("output_dir", "logs")
            silence_threshold = self.audio_recording_config.get(
                "silence_threshold", 3000
            )
            silence_duration = self.audio_recording_config.get("silence_duration", 2.0)
            quiet_threshold = self.audio_recording_config.get("quiet_threshold", 20)

            # Create audio buffer for silence detection and audio data management
            audio_buffer = AudioBuffer(
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

            # Create audio recorder that uses the audio buffer
            self.audio_recorders[conversation_id] = AudioRecorder(
                conversation_id=conversation_id,
                audio_buffer=audio_buffer,
                output_dir=output_dir,
                sample_rate=8000,  # WxCC compatible sample rate
                bit_depth=8,       # WxCC compatible bit depth
                channels=1,        # WxCC compatible channels
                encoding="ulaw",   # WxCC compatible encoding
                logger=self.logger,
            )

            self.logger.info(
                f"Initialized audio recorder for conversation {conversation_id} "
                f"(silence threshold: {silence_threshold}, duration: {silence_duration}s, "
                f"quiet threshold: {quiet_threshold}, output: {output_dir})"
            )
        except Exception as e:
            self.logger.error(f"Failed to initialize audio recorder: {e}")
            # Don't raise the exception, continue without recording

    def _process_audio_for_recording(self, audio_data, conversation_id: str) -> None:
        """
        Process audio data for recording.

        Args:
            audio_data: Audio data to record (bytes, bytearray, or str)
            conversation_id: Unique identifier for the conversation
        """
        if not self.record_caller_audio or not audio_data:
            return

        # Initialize recorder if not already done
        if conversation_id not in self.audio_recorders:
            self._init_audio_recorder(conversation_id)

        if conversation_id not in self.audio_recorders:
            # Initialization failed
            return

        try:
            # Use the parent class method to extract audio bytes
            audio_bytes = self.extract_audio_data(audio_data, conversation_id, self.logger)

            # Ensure we have valid audio bytes before proceeding
            if audio_bytes is None:
                self.logger.error(f"Failed to extract audio data for conversation {conversation_id}")
                return

            # Try to detect the actual audio format based on the data characteristics
            detected_encoding = self.audio_converter.detect_audio_encoding(audio_bytes)
            self.logger.debug(f"Detected audio encoding: {detected_encoding}")

            # Process audio format if needed
            processed_audio, final_encoding = self.process_audio_format(audio_bytes, detected_encoding, conversation_id)

            # Start recording if not already started
            audio_recorder = self.audio_recorders[conversation_id]
            if not audio_recorder.is_recording():
                audio_recorder.start_recording()

            # Add audio data to the recorder (which will use the audio buffer)
            audio_recorder.add_audio_data(processed_audio, final_encoding)
        except Exception as e:
            self.logger.error(
                f"Error recording audio for conversation {conversation_id}: {e}"
            )
            # Don't raise the exception, continue without recording



    def _convert_audio_to_wxcc_format(self, audio_path: Path) -> bytes:
        """
        Convert local audio file to WXCC-compatible format (8kHz, 8-bit u-law).

        Args:
            audio_path: Path to the audio file to convert

        Returns:
            Audio data in WXCC-compatible WAV format (8kHz, 8-bit u-law)
        """
        try:
            # Use the centralized audio conversion utility
            return self.audio_converter.convert_any_audio_to_wxcc(audio_path)
        except Exception as e:
            self.logger.error(f"Error converting audio file {audio_path}: {e}")
            # Return empty bytes if conversion fails
            return b""
