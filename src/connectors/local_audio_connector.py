"""
Local Audio Connector implementation.

This connector simulates a virtual agent by playing local audio files.
It's useful for testing and development purposes.
"""

import base64
import logging
import struct
from pathlib import Path
from typing import Any, Dict, List

from ..utils.audio_utils import AudioConverter, AudioRecorder
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
            self.logger.info(
                f"Ignoring conversation start event in send_message for conversation {conversation_id}"
            )
            return {
                "audio_content": b"",
                "text": "",
                "conversation_id": conversation_id,
                "agent_id": self.agent_id,
                "message_type": "silence",
                "barge_in_enabled": False,
            }

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
                    return {
                        "audio_content": audio_bytes,
                        "text": "Transferring you to an agent. Please wait.",
                        "conversation_id": conversation_id,
                        "agent_id": self.agent_id,
                        "message_type": "transfer",
                        "barge_in_enabled": False,
                    }

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
                    return {
                        "audio_content": audio_bytes,
                        "text": "Thank you for calling. Goodbye!",
                        "conversation_id": conversation_id,
                        "agent_id": self.agent_id,
                        "message_type": "goodbye",
                        "barge_in_enabled": False,
                    }

            # Return silence response for other DTMF inputs (no audio response)
            return {
                "audio_content": b"",
                "text": "",
                "conversation_id": conversation_id,
                "agent_id": self.agent_id,
                "message_type": "silence",
                "barge_in_enabled": False,
            }

        # Handle event inputs - log start and end of input events
        if message_data.get("input_type") == "event" and "event_data" in message_data:
            event_data = message_data.get("event_data", {})
            event_name = event_data.get("name", "")

            self.logger.info(f"Event for conversation {conversation_id}: {event_name}")

            # Return silence response for events (no audio response)
            return {
                "audio_content": b"",
                "text": "",
                "conversation_id": conversation_id,
                "agent_id": self.agent_id,
                "message_type": "silence",
                "barge_in_enabled": False,
            }

        # Handle audio input - return silence (no processing)
        if message_data.get("input_type") == "audio":
            self.logger.debug(
                f"Received audio input for conversation {conversation_id}"
            )

            # Record audio if enabled
            if self.record_caller_audio and "audio_data" in message_data:
                self._process_audio_for_recording(
                    message_data["audio_data"], conversation_id
                )

            return {
                "audio_content": b"",
                "text": "",
                "conversation_id": conversation_id,
                "agent_id": self.agent_id,
                "message_type": "silence",
                "barge_in_enabled": False,
            }

        # Default: return silence for any other input type
        self.logger.debug(
            f"Unhandled input type for conversation {conversation_id}: {message_data.get('input_type')}"
        )
        return {
            "audio_content": b"",
            "text": "",
            "conversation_id": conversation_id,
            "agent_id": self.agent_id,
            "message_type": "silence",
            "barge_in_enabled": False,
        }

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
                {
                    "event_type": "CONVERSATION_END",
                    "event_data": {
                        "reason": "user_requested_end",
                        "conversation_id": response["conversation_id"],
                    },
                }
            )
        elif response["message_type"] == "transfer":
            response["output_events"].append(
                {
                    "event_type": "TRANSFER_TO_HUMAN",
                    "event_data": {
                        "reason": "user_requested_transfer",
                        "conversation_id": response["conversation_id"],
                    },
                }
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

            # Create audio recorder
            self.audio_recorders[conversation_id] = AudioRecorder(
                conversation_id=conversation_id,
                output_dir=output_dir,
                silence_threshold=silence_threshold,
                silence_duration=silence_duration,
                logger=self.logger,
            )

            self.logger.info(
                f"Initialized audio recorder for conversation {conversation_id} "
                f"(silence threshold: {silence_threshold}, duration: {silence_duration}s, output: {output_dir})"
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
            # Initialize audio_bytes variable
            audio_bytes = None

            # Add detailed logging of the initial audio_data type
            self.logger.debug(
                f"Processing audio data of type {type(audio_data)} for {conversation_id}"
            )

            # Ensure audio_data is bytes - handle various input types
            if isinstance(audio_data, dict):
                # Extract audio data from dictionary
                self.logger.debug(
                    f"Audio data is dictionary with keys: {list(audio_data.keys())}"
                )
                if "audio_data" in audio_data:
                    self.logger.debug(
                        f"Extracting audio data from dictionary key 'audio_data' for {conversation_id}"
                    )
                    audio_data = audio_data["audio_data"]
                    self.logger.debug(f"Extracted audio data type: {type(audio_data)}")
                    audio_bytes = audio_data  # Assign extracted bytes to audio_bytes
                else:
                    # Try to find any key that might contain audio data
                    audio_keys = [k for k in audio_data.keys() if "audio" in k.lower()]
                    if audio_keys:
                        key = audio_keys[0]
                        self.logger.debug(
                            f"Found audio data under key '{key}' for {conversation_id}"
                        )
                        audio_data = audio_data[key]
                        self.logger.debug(f"Extracted audio data type: {type(audio_data)}")
                        audio_bytes = audio_data  # Assign extracted bytes to audio_bytes
                    else:
                        self.logger.error(
                            f"No audio data found in dictionary for {conversation_id}. Keys: {list(audio_data.keys())}"
                        )
                        return
            elif isinstance(audio_data, str):
                self.logger.debug(f"Audio data is string type, length: {len(audio_data)}")
                # If string is empty or None, log error and return
                if not audio_data:
                    self.logger.error(f"Empty string audio data received for {conversation_id}")
                    return

                # Only log full audio data in debug mode
                if self.logger.isEnabledFor(logging.DEBUG):
                    # Log the first few characters to understand the format
                    first_chars = audio_data[:100].replace('\n', '\\n').replace('\r', '\\r')
                    self.logger.debug(
                        f"Converting string audio data to bytes for {conversation_id}, data preview: '{first_chars}...'"
                    )
                else:
                    self.logger.debug(
                        f"Converting string audio data to bytes for {conversation_id} (length: {len(audio_data)})"
                    )

                # Try to convert from base64 string
                try:
                    # Try to decode as base64 first
                    self.logger.debug(f"Attempting base64 decode for {conversation_id}")
                    audio_bytes = base64.b64decode(audio_data)
                    self.logger.debug(f"Base64 decode successful, got {len(audio_bytes)} bytes")
                except Exception as e:
                    self.logger.debug(f"Base64 decode failed: {e}, trying direct encoding")
                    # If not base64, try direct encoding
                    audio_bytes = audio_data.encode(
                        "latin1"
                    )  # Use latin1 to preserve byte values
                    self.logger.debug(f"Direct encoding successful, got {len(audio_bytes)} bytes")
            elif isinstance(audio_data, (bytes, bytearray)):
                self.logger.debug(f"Audio data is already in bytes type, length: {len(audio_data)}")
                # If bytes are empty, log error and return
                if not audio_data:
                    self.logger.error(f"Empty bytes audio data received for {conversation_id}")
                    return

                # Only log full audio data in debug mode
                if self.logger.isEnabledFor(logging.DEBUG):
                    # Convert bytes to hex for better visibility in logs
                    hex_preview = audio_data[:50].hex()
                    self.logger.debug(
                        f"Processing bytes audio data for {conversation_id}, hex preview: {hex_preview}..."
                    )
                else:
                    self.logger.debug(
                        f"Processing bytes audio data for {conversation_id} (length: {len(audio_data)})"
                    )
                audio_bytes = audio_data
            else:
                self.logger.error(
                    f"Unsupported audio data type: {type(audio_data)} for {conversation_id}"
                )
                return

            # Ensure we have valid audio bytes before proceeding
            if audio_bytes is None:
                self.logger.error(f"Failed to convert audio data to bytes for {conversation_id}")
                return

            # Add audio data to recorder
            self.audio_recorders[conversation_id].add_audio_data(audio_bytes, "ulaw")
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
            import wave

            # Check if file exists
            if not audio_path.exists():
                self.logger.error(f"Audio file not found: {audio_path}")
                return b""

            # Get original file size
            original_size = audio_path.stat().st_size
            self.logger.info(f"Original file size: {original_size} bytes")

            # Read the original WAV file
            with wave.open(str(audio_path), "rb") as wav_file:
                # Get file properties
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                sample_rate = wav_file.getframerate()
                n_frames = wav_file.getnframes()
                compression_type = wav_file.getcomptype()

                self.logger.info(f"Converting audio file: {audio_path}")
                self.logger.info(
                    f"Original format: {sample_rate}Hz, {sample_width * 8}bit, {channels} channel(s), compression: {compression_type}"
                )
                self.logger.info(
                    f"Original frames: {n_frames}, duration: {n_frames / sample_rate:.2f}s"
                )

                # Read all audio data
                pcm_data = wav_file.readframes(n_frames)
                self.logger.info(f"Read PCM data: {len(pcm_data)} bytes")

                # Determine bit depth from sample width
                bit_depth = sample_width * 8

                # Convert to WXCC-compatible format
                if sample_rate != 8000 or bit_depth != 8 or compression_type != b"NONE":
                    self.logger.info(
                        "Converting audio to WXCC-compatible format (8kHz, 8-bit u-law)"
                    )

                    # Step 1: Resample if needed
                    if sample_rate != 8000:
                        if sample_rate == 16000:
                            pcm_data = self.audio_converter.resample_16khz_to_8khz(
                                pcm_data, bit_depth
                            )
                            self.logger.info(
                                f"Resampled from {sample_rate}Hz to 8kHz: {len(pcm_data)} bytes"
                            )
                        elif sample_rate == 24000:
                            # For 24kHz, we need to resample to 8kHz (take every 3rd sample)
                            if bit_depth == 16:
                                samples_24khz = struct.unpack(
                                    f"<{len(pcm_data) // 2}h", pcm_data
                                )
                                samples_8khz = samples_24khz[
                                    ::3
                                ]  # Take every 3rd sample
                                pcm_data = struct.pack(
                                    f"<{len(samples_8khz)}h", *samples_8khz
                                )
                                self.logger.info(
                                    f"Resampled from {sample_rate}Hz to 8kHz: {len(pcm_data)} bytes"
                                )
                            else:
                                # For 8-bit, take every 3rd byte
                                pcm_data = pcm_data[::3]
                                self.logger.info(
                                    f"Resampled from {sample_rate}Hz to 8kHz: {len(pcm_data)} bytes"
                                )
                        else:
                            self.logger.warning(
                                f"Unsupported sample rate: {sample_rate}Hz, using original"
                            )

                    # Step 2: Convert to u-law if needed
                    if bit_depth != 8 or compression_type != b"NONE":
                        pcm_data = self.audio_converter.pcm_to_ulaw(
                            pcm_data, sample_rate=8000, bit_depth=16
                        )
                        self.logger.info(
                            f"Converted PCM to u-law format: {len(pcm_data)} bytes"
                        )

                    # Step 3: Convert to WAV format with proper headers
                    wav_data = self.audio_converter.pcm_to_wav(
                        pcm_data,
                        sample_rate=8000,  # WXCC expects 8kHz
                        bit_depth=8,  # WXCC expects 8-bit
                        channels=1,  # WXCC expects mono
                        encoding="ulaw",  # WXCC expects u-law
                    )

                    self.logger.info(
                        f"Successfully converted to WXCC-compatible format: {len(wav_data)} bytes"
                    )
                    self.logger.info(
                        f"Conversion ratio: {len(wav_data) / original_size:.2f}x"
                    )
                    return wav_data
                else:
                    # Already in correct format, just return as-is
                    self.logger.info("Audio file already in WXCC-compatible format")
                    return pcm_data

        except Exception as e:
            self.logger.error(f"Error converting audio file {audio_path}: {e}")
            import traceback

            self.logger.error(f"Traceback: {traceback.format_exc()}")
            # Return empty bytes if conversion fails
            return b""
