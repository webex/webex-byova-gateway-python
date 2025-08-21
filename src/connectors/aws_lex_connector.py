"""
AWS Lex Connector for Webex Contact Center BYOVA Gateway.

This connector integrates with AWS Lex v2 to provide virtual agent capabilities.
It handles basic agent discovery and conversation initialization.
"""

import boto3
import logging
from botocore.exceptions import ClientError
from typing import Any, Dict, List

from .i_vendor_connector import IVendorConnector
from ..utils.audio_utils import convert_aws_lex_audio_to_wxcc, AudioRecorder


class AWSLexConnector(IVendorConnector):
    """
    AWS Lex v2 connector for virtual agent integration.

    This connector provides a simple interface to AWS Lex bots using the
    standard TSTALIASID alias that most Lex bots have by default.

    Bot Configuration:
    - bot_alias_id: Bot alias ID to use for conversations (default: TSTALIASID)

    WxCC Audio Requirements:
    - Sample Rate: 8000 Hz (8kHz) - REQUIRED to avoid 5-second delays
    - Bit Depth: 8-bit - REQUIRED for proper audio playback
    - Encoding: u-law - REQUIRED for WxCC compatibility
    - Channels: 1 (mono) - REQUIRED for WxCC compatibility

    Audio Conversion:
    This connector automatically handles the complete audio format conversion
    from AWS Lex's 16kHz PCM to WxCC's required 8kHz u-law format using
    the shared audio utilities.

    Note: AWS Lex returns raw PCM audio data, but WxCC requires u-law encoded WAV files.
    The audio utilities automatically handle all necessary conversions.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the AWS Lex connector.

        Args:
            config: Configuration dictionary containing:
                - region_name: AWS region (required)
                - aws_access_key_id: AWS access key (optional, uses default chain)
                - aws_secret_access_key: AWS secret key (optional, uses default chain)
                - bot_alias_id: Bot alias ID to use for conversations (default: TSTALIASID)

        Note: WxCC requires 8kHz, 8-bit u-law, mono audio to avoid 5-second delays.
        AWS Lex returns 16kHz, 16-bit PCM, which this connector automatically converts
        using the shared audio utilities.
        """
        # Extract configuration
        self.region_name = config.get('region_name')
        if not self.region_name:
            raise ValueError("region_name is required in AWS Lex connector configuration")

        # Optional explicit AWS credentials
        self.aws_access_key_id = config.get('aws_access_key_id')
        self.aws_secret_access_key = config.get('aws_secret_access_key')

        # Audio format configuration for WAV conversion
        # WxCC always requires WAV format, so this is always enabled

        # Bot alias configuration
        self.bot_alias_id = config.get('bot_alias_id', 'TSTALIASID')  # Default: TSTALIASID

        # Set up logging
        self.logger = logging.getLogger(__name__)

        # Initialize AWS clients
        self._init_aws_clients()

        # Cache for available bots
        self._available_bots = None

        # Mapping from display names to actual bot IDs
        self._bot_name_to_id_map = {}

        # Simple session storage for conversations
        self._sessions = {}

        # Audio buffering configuration - always enabled for AWS Lex connector
        self.audio_buffers = {}  # Dictionary to store audio buffers by conversation ID

        # Get audio buffering configuration
        self.audio_buffering_config = config.get("audio_recording", {})

        self.logger.info("Caller audio buffering is enabled")

        self.logger.info(f"AWSLexConnector initialized for region: {self.region_name}")
        self.logger.info(f"Bot alias ID: {self.bot_alias_id}")
        self.logger.info("Audio conversion to WAV format: Always enabled (WxCC requirement)")

    def _init_aws_clients(self) -> None:
        """Initialize AWS Lex clients."""
        try:
            if self.aws_access_key_id and self.aws_secret_access_key:
                # Use explicit credentials
                session = boto3.Session(
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                    region_name=self.region_name
                )
                self.logger.info("Using explicit AWS credentials")
            else:
                # Use default credential chain
                session = boto3.Session(region_name=self.region_name)
                self.logger.info("Using default AWS credential chain")

            # Initialize clients
            self.lex_client = session.client('lexv2-models')  # For bot managemen
            self.lex_runtime = session.client('lexv2-runtime')  # For conversations

            self.logger.info("AWS Lex clients initialized successfully")

        except Exception as e:
            self.logger.error(f"Failed to initialize AWS clients: {e}")
            raise

    def get_available_agents(self) -> List[str]:
        """
        Get available virtual agent IDs from AWS Lex.

        Returns:
            List of Lex bot IDs that can be used as virtual agents
        """
        if self._available_bots is None:
            try:
                self.logger.info("Fetching available Lex bots...")

                # List all bots in the region
                response = self.lex_client.list_bots()
                bots = response.get('botSummaries', [])

                # Extract bot IDs and names, format as "aws_lex_connector: Bot Name"
                bot_identifiers = []
                for bot in bots:
                    bot_id = bot['botId']
                    bot_name = bot.get('botName', bot_id)  # Use bot name if available, fallback to ID
                    display_name = f"aws_lex_connector: {bot_name}"

                    # Store the mapping: display_name -> actual_bot_id
                    self._bot_name_to_id_map[display_name] = bot_id

                    bot_identifiers.append(display_name)

                self._available_bots = bot_identifiers
                self.logger.info(f"Found {len(bot_identifiers)} available Lex bots: {bot_identifiers}")
                self.logger.info(f"Bot mappings: {self._bot_name_to_id_map}")

            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_message = e.response['Error']['Message']
                self.logger.error(f"AWS Lex API error ({error_code}): {error_message}")
                self._available_bots = []
            except Exception as e:
                self.logger.error(f"Unexpected error fetching Lex bots: {e}")
                self._available_bots = []

        return self._available_bots

    def start_conversation(self, conversation_id: str, request_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Start a new conversation with a Lex bot.

        Args:
            conversation_id: Unique conversation identifier
            request_data: Request data containing virtual_agent_id

        Returns:
            Response data for the new conversation with audio from Lex
        """
        try:
            # Get the display name from WxCC (e.g., "aws_lex_connector: Booking")
            display_name = request_data.get("virtual_agent_id", "")

            # Look up the actual bot ID from our mapping
            actual_bot_id = self._bot_name_to_id_map.get(display_name)
            if not actual_bot_id:
                raise ValueError(f"Bot not found in mapping: {display_name}. Available bots: {list(self._bot_name_to_id_map.keys())}")

            # Extract the friendly bot name for display
            bot_name = display_name.split(": ", 1)[1] if ": " in display_name else display_name

            # Create a simple session ID for Lex
            session_id = f"session_{conversation_id}"

            # Store session info with both names
            self._sessions[conversation_id] = {
                "session_id": session_id,
                "display_name": display_name,      # "aws_lex_connector: Booking"
                "actual_bot_id": actual_bot_id,    # "E7LNGX7D2J"
                "bot_name": bot_name               # "Booking"
            }

            self.logger.info(f"Started Lex conversation: {conversation_id} with bot: {bot_name} (ID: {actual_bot_id})")
            self.logger.info(f"Using bot alias: {self.bot_alias_id}")

            # Send initial text to Lex and get audio response
            try:
                # Convert text to bytes for the reques
                text_input = "I need to book a hotel room"
                text_bytes = text_input.encode('utf-8')

                self.logger.info(f"Sending initial text to Lex: '{text_input}'")

                response = self.lex_runtime.recognize_utterance(
                    botId=actual_bot_id,
                    botAliasId=self.bot_alias_id,
                    localeId='en_US',
                    sessionId=session_id,
                    requestContentType='text/plain; charset=utf-8',
                    responseContentType='audio/pcm',
                    inputStream=text_bytes
                )

                self.logger.info(f"Lex API response received: {type(response)}")
                self.logger.info(f"Lex API response keys: {list(response.keys()) if hasattr(response, 'keys') else 'No keys'}")

                # Extract audio response
                audio_stream = response.get('audioStream')
                if audio_stream:
                    self.logger.info(f"Audio stream found: {type(audio_stream)}")
                    audio_response = audio_stream.read()
                    audio_stream.close()
                    self.logger.info(f"Received audio response from Lex (size: {len(audio_response)} bytes)")

                    if audio_response:
                        self.logger.info("Audio content is valid, returning response with audio")

                        # Use the audio utility to convert AWS Lex audio to WxCC-compatible forma
                        # AWS Lex returns 16kHz, 16-bit PCM, but WxCC expects 8kHz, 8-bit u-law
                        wav_audio, content_type = convert_aws_lex_audio_to_wxcc(
                            audio_response,
                            bit_depth=16       # Lex returns 16-bit PCM
                        )

                        return self.create_response(
                            conversation_id=conversation_id,
                            message_type="welcome",
                            text=f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                            audio_content=wav_audio,
                            barge_in_enabled=True,
                            content_type=content_type,
                            response_type="final"
                        )
                    else:
                        self.logger.warning("Audio stream was empty, falling back to text-only response")
                        return self.create_response(
                            conversation_id=conversation_id,
                            message_type="welcome",
                            text=f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                            audio_content=b"",
                            barge_in_enabled=False,
                            response_type="final"
                        )
                else:
                    self.logger.error("No audio stream in Lex response")
                    # Check if there are other fields in the response
                    if hasattr(response, 'messages'):
                        self.logger.info(f"Lex messages: {response.messages}")
                    if hasattr(response, 'intentName'):
                        self.logger.info(f"Lex intent: {response.intentName}")

                    return self.create_response(
                        conversation_id=conversation_id,
                        message_type="welcome",
                        text=f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                        audio_content=b"",
                        barge_in_enabled=False,
                        response_type="final"
                    )

            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_message = e.response['Error']['Message']
                self.logger.error(f"Lex API error during conversation start: {error_code} - {error_message}")

                # Fallback to text response
                return self.create_response(
                    conversation_id=conversation_id,
                    message_type="welcome",
                    text=f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                    audio_content=b"",
                    barge_in_enabled=True,
                    response_type="final"
                )

            except Exception as e:
                self.logger.error(f"Error getting audio response from Lex: {e}")
                self.logger.error(f"Exception type: {type(e)}")
                import traceback
                self.logger.error(f"Traceback: {traceback.format_exc()}")

                # Fallback to text response
                return self.create_response(
                    conversation_id=conversation_id,
                    message_type="welcome",
                    text=f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                    audio_content=b"",
                    barge_in_enabled=True,
                    response_type="final"
                )

        except Exception as e:
            self.logger.error(f"Error starting Lex conversation: {e}")
            self.logger.error(f"Exception type: {type(e)}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return self.create_response(
                conversation_id=conversation_id,
                message_type="error",
                text="I'm having trouble starting our conversation. Please try again.",
                audio_content=b"",
                barge_in_enabled=False,
                response_type="final"
            )

    def send_message(self, conversation_id: str, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a message to the AWS Lex bot and get a response.

        Args:
            conversation_id: Active conversation identifier
            message_data: Message data containing input (audio or text)

        Returns:
            Response from Lex containing audio and tex
        """
        self.logger.info(f"Processing message for conversation {conversation_id}")

        # Log relevant parts of message_data without audio bytes
        log_data = {
            "conversation_id": message_data.get("conversation_id"),
            "virtual_agent_id": message_data.get("virtual_agent_id"),
            "input_type": message_data.get("input_type"),
        }
        self.logger.debug(f"Message data for conversation {conversation_id}: {log_data}")

        # Check if we have a valid session for this conversation
        if conversation_id not in self._sessions:
            self.logger.error(f"No active session found for conversation {conversation_id}")
            return self.create_response(
                conversation_id=conversation_id,
                message_type="error",
                text="No active conversation found. Please start a new conversation.",
                audio_content=b"",
                barge_in_enabled=False,
                response_type="final"
            )

        # Get session info
        session_info = self._sessions[conversation_id]
        session_id = session_info["session_id"]
        bot_id = session_info["actual_bot_id"]
        bot_name = session_info["bot_name"]

        # Handle conversation start events
        if message_data.get("input_type") == "conversation_start":
            return self.handle_conversation_start(conversation_id, message_data, self.logger)

        # Handle DTMF input
        if message_data.get("input_type") == "dtmf" and "dtmf_data" in message_data:
            return self._handle_dtmf_input(conversation_id, message_data, bot_name)

        # Handle event input
        if message_data.get("input_type") == "event":
            return self.handle_event(conversation_id, message_data, self.logger)

        # Handle audio input
        if message_data.get("input_type") == "audio":
            return self._handle_audio_input(conversation_id, message_data, bot_id, session_id, bot_name)

        # Handle unrecognized input
        return self.handle_unrecognized_input(conversation_id, message_data, self.logger)

    def _handle_dtmf_input(self, conversation_id: str, message_data: Dict[str, Any], bot_name: str) -> Dict[str, Any]:
        """
        Handle DTMF input for the Lex bot.

        Args:
            conversation_id: Conversation identifier
            message_data: Message data containing DTMF input
            bot_name: Name of the bo

        Returns:
            Response based on DTMF input
        """
        dtmf_data = message_data.get("dtmf_data", {})
        dtmf_events = dtmf_data.get("dtmf_events", [])

        if dtmf_events:
            self.logger.info(f"Received DTMF input for conversation {conversation_id}: {dtmf_events}")
            # Convert DTMF events to a string
            dtmf_string = "".join([str(digit) for digit in dtmf_events])

            # Process special DTMF codes
            if "5" in dtmf_string:  # Transfer code
                self.logger.info(f"DTMF transfer requested for conversation {conversation_id}")
                return self.create_response(
                    conversation_id=conversation_id,
                    message_type="transfer",
                    text=f"Transferring you from the {bot_name} assistant to a live agent.",
                    audio_content=b"",  # Would need to load transfer audio here
                    barge_in_enabled=False,
                    response_type="final"
                )
            elif "6" in dtmf_string:  # Goodbye code
                self.logger.info(f"DTMF goodbye requested for conversation {conversation_id}")
                return self.create_response(
                    conversation_id=conversation_id,
                    message_type="goodbye",
                    text=f"Goodbye from the {bot_name} assistant. Thank you for your time.",
                    audio_content=b"",  # Would need to load transfer audio here
                    barge_in_enabled=False,
                    response_type="final"
                )
            else:
                # For other DTMF digits, send to Lex as tex
                self.logger.info(f"Sending DTMF {dtmf_string} to Lex for conversation {conversation_id}")
                # Convert DTMF to a more meaningful input for Lex
                text_input = f"DTMF {dtmf_string}"
                return self._send_text_to_lex(conversation_id, text_input)

        # If no DTMF events, just return silence
        return self.create_response(
            conversation_id=conversation_id,
            message_type="silence",
            response_type="final"
        )

    def _handle_audio_input(self, conversation_id: str, message_data: Dict[str, Any],
                          bot_id: str, session_id: str, bot_name: str) -> Dict[str, Any]:
        """
        Handle audio input for the Lex bot.

        Args:
            conversation_id: Conversation identifier
            message_data: Message data containing audio inpu
            bot_id: Lex bot ID
            session_id: Lex session ID
            bot_name: Name of the bo

        Returns:
            Response from Lex with processed audio
        """
        try:
            # Extract audio data from the message
            audio_bytes = self.extract_audio_data(message_data.get("audio_data"), conversation_id, self.logger)

            if not audio_bytes:
                self.logger.error(f"No valid audio data found for conversation {conversation_id}")
                return self.create_response(
                    conversation_id=conversation_id,
                    message_type="error",
                    text="I couldn't hear you. Please try speaking again.",
                    audio_content=b"",
                    barge_in_enabled=True,
                    response_type="final"
                )

            # Buffer audio (always enabled for AWS Lex connector)
            self._process_audio_for_buffering(audio_bytes, conversation_id)

            # AWS Lex requires specific audio format
            # We're using linear 16-bit PCM at 16kHz sample rate with a single channel
            # If needed, add audio conversion logic here to ensure compatibility

            # TODO: Send audio to AWS Lex here
            # For now, return a placeholder response
            return self.create_response(
                conversation_id=conversation_id,
                message_type="silence",
                text="Audio received and buffered. AWS Lex integration pending.",
                barge_in_enabled=True,
                response_type="silence"
            )

        except Exception as e:
            self.logger.error(f"Error processing audio input: {e}")
            return self.create_response(
                conversation_id=conversation_id,
                message_type="error",
                text="An error occurred while processing your audio. Please try again.",
                barge_in_enabled=True,
                response_type="final"
            )

    def _send_text_to_lex(self, conversation_id: str, text_input: str) -> Dict[str, Any]:
        """
        Send text input to Lex and process the response.

        Args:
            conversation_id: Conversation identifier
            text_input: Text to send to Lex

        Returns:
            Response from Lex with processed audio
        """
        try:
            # Extract session info
            session_info = self._get_session_info(conversation_id)
            if not session_info:
                self.logger.error(f"No session found for conversation {conversation_id}")
                return self.create_response(
                    conversation_id=conversation_id,
                    message_type="error",
                    text="I couldn't process your request. Please try again.",
                    barge_in_enabled=True,
                    response_type="final"
                )

            self.logger.info(f"Sending text '{text_input}' to Lex for conversation {conversation_id}")

            # This is a placeholder for the actual Lex text implementation
            self.logger.info(f"Text functionality not yet fully implemented: {text_input}")
            # Return a placeholder response until full implementation is complete
            return self.create_response(
                conversation_id=conversation_id,
                message_type="silence",
                text=f"Processing text input: {text_input}",
                barge_in_enabled=True,
                response_type="final"
            )
        except Exception as e:
            self.logger.error(f"Error processing text input: {e}")
            return self.create_response(
                conversation_id=conversation_id,
                message_type="error",
                text="An error occurred while processing your text. Please try again.",
                barge_in_enabled=True,
                response_type="final"
            )

    def end_conversation(self, conversation_id: str, message_data: Dict[str, Any] = None) -> None:
        """
        End an active conversation and clean up resources.

        Args:
            conversation_id: Active conversation identifier
            message_data: Optional final message data
        """
        # Log conversation details first, in case there's an error in cleanup
        self.logger.info(f"Ending AWS Lex conversation: {conversation_id}")

        # Check if we have a valid session for this conversation
        if conversation_id in self._sessions:
            # Extract useful info for logging before we clean up
            session_info = self._sessions[conversation_id]
            bot_name = session_info.get("bot_name", "unknown")
            session_id = session_info.get("session_id", "unknown")
            bot_id = session_info.get("actual_bot_id", "unknown")

            # Clean up the session
            del self._sessions[conversation_id]

            # Detailed logging with session info
            self.logger.info(
                f"Ended AWS Lex conversation - ID: {conversation_id}, "
                f"Bot: {bot_name}, Session ID: {session_id}, Bot ID: {bot_id}"
            )

            # If we have message data, generate a proper goodbye response
            if message_data and message_data.get("generate_response", False):
                self.logger.debug(f"Creating goodbye response for conversation {conversation_id}")
                # Could return a response here if needed by the caller
                return
        else:
            self.logger.warning(f"Attempted to end non-existent conversation: {conversation_id}")

        # Finalize audio buffering (always enabled for AWS Lex connector)
        if conversation_id in self.audio_buffers:
            try:
                # Finalize the buffering
                self.audio_buffers[conversation_id].finalize_recording()
                self.logger.info(f"Finalized audio buffering for conversation {conversation_id}")
                
                # Clean up the buffer
                del self.audio_buffers[conversation_id]
            except Exception as e:
                self.logger.error(f"Error finalizing audio buffering for conversation {conversation_id}: {e}")

        # No return value needed for normal end_conversation calls

    def convert_wxcc_to_vendor(self, wxcc_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert Webex Contact Center data format to vendor format.

        Args:
            wxcc_data: Data in WxCC forma

        Returns:
            Data converted to vendor forma
        """
        # For now, just return the data as-is
        # This can be enhanced later for specific format conversions
        return wxcc_data

    def convert_vendor_to_wxcc(self, vendor_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert vendor data format to Webex Contact Center format.

        Args:
            vendor_data: Data in vendor forma

        Returns:
            Data converted to WxCC forma
        """
        # For now, just return the data as-is
        # This can be enhanced later for specific format conversions
        return vendor_data

    def _refresh_bot_cache(self) -> None:
        """Refresh the cached list of available bots."""
        self._available_bots = None
        self._bot_name_to_id_map = {}  # Clear the mapping cache too
        self.get_available_agents()

    def _init_audio_buffer(self, conversation_id: str) -> None:
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
            output_dir = self.audio_buffering_config.get("output_dir", "logs")
            silence_threshold = self.audio_buffering_config.get(
                "silence_threshold", 3000
            )
            silence_duration = self.audio_buffering_config.get("silence_duration", 2.0)
            quiet_threshold = self.audio_buffering_config.get("quiet_threshold", 20)

            # Create audio buffer with callback
            self.audio_buffers[conversation_id] = AudioRecorder(
                conversation_id=conversation_id,
                output_dir=output_dir,
                silence_threshold=silence_threshold,
                silence_duration=silence_duration,
                quiet_threshold=quiet_threshold,
                buffer_only=True,  # We only want to buffer, not save files
                on_audio_ready=self._on_audio_ready_callback,
                logger=self.logger,
            )

            self.logger.info(
                f"Initialized audio buffer for conversation {conversation_id} "
                f"(silence threshold: {silence_threshold}, duration: {silence_duration}s, "
                f"quiet threshold: {quiet_threshold}, output: {output_dir})"
            )
        except Exception as e:
            self.logger.error(f"Failed to initialize audio buffer: {e}")
            # Don't raise the exception, continue without buffering

    def _on_audio_ready_callback(self, conversation_id: str, audio_data: bytes) -> None:
        """
        Callback function called when audio segment is ready.

        Args:
            conversation_id: Unique identifier for the conversation
            audio_data: Audio data bytes that are ready for processing
        """
        try:
            # Log information about the buffered audio
            buffer_size = len(audio_data)
            
            # Calculate estimated duration at different sample rates
            duration_8khz = buffer_size / 8000
            duration_16khz = buffer_size / 16000
            
            # Detect actual audio encoding using audio utilities
            from ..utils.audio_utils import AudioConverter
            audio_converter = AudioConverter(self.logger)
            detected_encoding = audio_converter.detect_audio_encoding(audio_data)
            
            # Log detailed audio format information
            self.logger.info(
                f"Audio segment ready for conversation {conversation_id}: "
                f"Size: {buffer_size} bytes, "
                f"Duration: ~{duration_8khz:.2f}s (8kHz) / ~{duration_16khz:.2f}s (16kHz), "
                f"Detected format: {detected_encoding}, "
                f"Ready to send to AWS Lex"
            )
            
            # Log additional format details
            self.logger.info(
                f"Audio format details for conversation {conversation_id}: "
                f"Raw data length: {buffer_size} bytes, "
                f"Sample rate compatibility: 8kHz ({duration_8khz:.2f}s) / 16kHz ({duration_16khz:.2f}s), "
                f"Data type: bytes, "
                f"Detected encoding: {detected_encoding}"
            )
            
            # TODO: Send audio_data to AWS Lex here
            # For now, just log that we would send it
            self.logger.info(
                f"Would send {buffer_size} bytes of audio to AWS Lex for conversation {conversation_id}"
            )
            
        except Exception as e:
            self.logger.error(
                f"Error in audio ready callback for conversation {conversation_id}: {e}"
            )

    def _process_audio_for_buffering(self, audio_data, conversation_id: str) -> None:
        """
        Process audio data for buffering.

        Args:
            audio_data: Audio data to buffer (bytes, bytearray, or str)
            conversation_id: Unique identifier for the conversation
        """
        if not audio_data:
            return

        # Initialize buffer if not already done
        if conversation_id not in self.audio_buffers:
            self._init_audio_buffer(conversation_id)

        if conversation_id not in self.audio_buffers:
            # Initialization failed
            return

        try:
            # Use the parent class method to extract audio bytes
            audio_bytes = self.extract_audio_data(audio_data, conversation_id, self.logger)

            # Ensure we have valid audio bytes before proceeding
            if audio_bytes is None:
                self.logger.error(f"Failed to extract audio data for conversation {conversation_id}")
                return

            # Add audio data to the buffer
            self.audio_buffers[conversation_id].add_audio_data(audio_bytes)
            
        except Exception as e:
            self.logger.error(
                f"Error buffering audio for conversation {conversation_id}: {e}"
            )
            # Don't raise the exception, continue without buffering
