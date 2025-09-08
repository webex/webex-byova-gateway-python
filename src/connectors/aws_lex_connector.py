"""
AWS Lex Connector for Webex Contact Center BYOVA Gateway.

This connector integrates with AWS Lex v2 to provide virtual agent capabilities.
It handles basic agent discovery and conversation initialization.
"""

import boto3
import logging
from botocore.exceptions import ClientError
from typing import Any, Dict, List, Iterator, Optional

from .i_vendor_connector import IVendorConnector
from .aws_lex_audio_processor import AWSLexAudioProcessor
from .aws_lex_session_manager import AWSLexSessionManager
from .aws_lex_response_handler import AWSLexResponseHandler
from .aws_lex_config import AWSLexConfig
from .aws_lex_error_handler import AWSLexErrorHandler, ErrorContext


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
                - audio_logging: Audio logging configuration (optional)

        Note: WxCC requires 8kHz, 8-bit u-law, mono audio to avoid 5-second delays.
        AWS Lex returns 16kHz, 16-bit PCM, which this connector automatically converts
        using the shared audio utilities.
        """
        # Set up logging first
        self.logger = logging.getLogger(__name__)

        # Initialize configuration manager
        self.config_manager = AWSLexConfig(config, self.logger)

        # Extract commonly used configuration values for efficiency
        self.region_name = self.config_manager.get_region_name()
        self.bot_alias_id = self.config_manager.get_bot_alias_id()
        self.locale_id = self.config_manager.get_locale_id()
        self.text_request_content_type = self.config_manager.get_text_request_content_type()
        self.audio_request_content_type = self.config_manager.get_audio_request_content_type()
        self.response_content_type = self.config_manager.get_response_content_type()
        self.barge_in_enabled = self.config_manager.is_barge_in_enabled()
        self.aws_credentials = self.config_manager.get_aws_credentials()

        # Initialize error handler first (needed for AWS client initialization)
        self.error_handler = AWSLexErrorHandler(self.logger)

        # Initialize AWS clients
        self._init_aws_clients()

        # Initialize session manager
        self.session_manager = AWSLexSessionManager(self.logger)
        
        # Initialize response handler
        self.response_handler = AWSLexResponseHandler(self.logger, self.error_handler, self.barge_in_enabled)

        # Initialize audio processor
        self.audio_processor = AWSLexAudioProcessor(config, self.logger)

        self.logger.debug("Caller audio buffering is enabled")

        self.logger.info(f"AWSLexConnector initialized: {self.config_manager.get_config_summary()}")
        self.logger.debug("Audio conversion to WAV format: Always enabled (WxCC requirement)")

    def _init_aws_clients(self) -> None:
        """Initialize AWS Lex clients."""
        try:
            if self.aws_credentials["aws_access_key_id"] and self.aws_credentials["aws_secret_access_key"]:
                # Use explicit credentials
                session = boto3.Session(
                    aws_access_key_id=self.aws_credentials["aws_access_key_id"],
                    aws_secret_access_key=self.aws_credentials["aws_secret_access_key"],
                    region_name=self.region_name
                )
                self.logger.debug("Using explicit AWS credentials")
            else:
                # Use default credential chain
                session = boto3.Session(region_name=self.region_name)
                self.logger.debug("Using default AWS credential chain")

            # Initialize clients
            self.lex_client = session.client('lexv2-models')  # For bot management
            self.lex_runtime = session.client('lexv2-runtime')  # For conversations

            self.logger.debug("AWS Lex clients initialized successfully")

        except Exception as e:
            self.error_handler.handle_aws_client_init_error(e)

    def get_available_agents(self) -> List[str]:
        """
        Get available virtual agent IDs from AWS Lex.

        Returns:
            List of Lex bot IDs that can be used as virtual agents
        """
        return self.session_manager.get_available_agents(self.lex_client)

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

            # Create session using session manager
            session_info = self.session_manager.create_session(conversation_id, display_name)
            actual_bot_id = session_info["actual_bot_id"]
            bot_name = session_info["bot_name"]
            session_id = session_info["session_id"]

            self.logger.debug(f"Using bot alias: {self.bot_alias_id}")

            # Send initial text to Lex and get audio response
            try:
                # Convert text to bytes for the request
                text_input = "I need to book a hotel room"
                text_bytes = text_input.encode('utf-8')

                self.logger.debug(f"Sending initial text to Lex: '{text_input}'")

                response = self.lex_runtime.recognize_utterance(
                    botId=actual_bot_id,
                    botAliasId=self.bot_alias_id,
                    localeId=self.locale_id,
                    sessionId=session_id,
                    requestContentType=self.text_request_content_type,
                    responseContentType=self.response_content_type,
                    inputStream=text_bytes
                )

                self.logger.debug(f"Lex API response received: {type(response)}")
                self.logger.debug(f"Lex API response keys: {list(response.keys()) if hasattr(response, 'keys') else 'No keys'}")

                # Process the Lex response using the comprehensive response handler method
                messages_data = self.response_handler._decode_lex_response('messages', response) or []
                
                # Use the official response handler method
                for response_dict in self.response_handler.process_lex_response(
                    conversation_id=conversation_id,
                    response=response,
                    messages_data=messages_data,
                    audio_processor=self.audio_processor,
                    session_manager=self.session_manager
                ):
                    return response_dict  # Return the first (and typically only) response

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
                    barge_in_enabled=self.barge_in_enabled,
                    response_type="final",
                    input_mode=3,  # INPUT_VOICE_DTMF = 3 (from protobuf)
                    input_handling_config={
                        "dtmf_config": {
                            "inter_digit_timeout_msec": 5000,  # 5 second timeout between digits
                            "dtmf_input_length": 10  # Allow up to 10 digits
                        }
                    }
                )

            except Exception as e:
                self.error_handler.handle_audio_processing_error(e, conversation_id)
                
                # Fallback to text response
                return self.create_response(
                    conversation_id=conversation_id,
                    message_type="welcome",
                    text=f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                    audio_content=b"",
                    barge_in_enabled=self.barge_in_enabled,
                    response_type="final",
                    input_mode=3,  # INPUT_VOICE_DTMF = 3 (from protobuf)
                    input_handling_config={
                        "dtmf_config": {
                            "inter_digit_timeout_msec": 5000,  # 5 second timeout between digits
                            "dtmf_input_length": 10  # Allow up to 10 digits
                        }
                    }
                )

        except Exception as e:
            self.error_handler.handle_conversation_error(e, conversation_id, ErrorContext.CONVERSATION_START)
            return self.error_handler.create_fallback_response(
                conversation_id=conversation_id,
                original_message_type="welcome",
                fallback_text="I'm having trouble starting our conversation. Please try again."
            )

    def send_message(self, conversation_id: str, message_data: Dict[str, Any]) -> Iterator[Optional[Dict[str, Any]]]:
        """
        Send a message to the AWS Lex bot and get a response.

        Args:
            conversation_id: Active conversation identifier
            message_data: Message data containing input (audio or text)

        Returns:
            Iterator yielding responses from Lex containing audio and text.
            Yield None when no response is needed.
        """
        self.logger.debug(f"Processing message for conversation {conversation_id}, input_type: {message_data.get('input_type')}")

        # Log relevant parts of message_data without audio bytes
        log_data = {
            "conversation_id": message_data.get("conversation_id"),
            "virtual_agent_id": message_data.get("virtual_agent_id"),
            "input_type": message_data.get("input_type"),
        }
        self.logger.debug(f"Message data for conversation {conversation_id}: {log_data}")

        # Check if we have a valid session for this conversation
        if not self.session_manager.has_session(conversation_id):
            self.logger.error(f"No active session found for conversation {conversation_id}")
            yield self.error_handler.create_session_error_response(conversation_id, ErrorContext.SESSION_NO_SESSION)
            return

        # Get session info
        session_id = self.session_manager.get_session_id(conversation_id)
        bot_id = self.session_manager.get_bot_id(conversation_id)
        bot_name = self.session_manager.get_bot_name(conversation_id)

        # Handle conversation start events
        if message_data.get("input_type") == "conversation_start":
            yield self.handle_conversation_start(conversation_id, message_data, self.logger)
            return

        # Handle DTMF input
        if message_data.get("input_type") == "dtmf":
            yield self._handle_dtmf_input(conversation_id, message_data, bot_id, session_id, bot_name)
            return

        # Handle audio input
        if message_data.get("input_type") == "audio":
            yield from self._handle_audio_input(conversation_id, message_data, bot_id, session_id, bot_name)
            return

        # Handle event input
        if message_data.get("input_type") == "event":
            yield self.handle_event(conversation_id, message_data, self.logger)
            return

        # Handle unrecognized input types
        response = self.handle_unrecognized_input(conversation_id, message_data, self.logger)
        if response is not None:
            yield response

    def handle_event(self, conversation_id: str, message_data: Dict[str, Any], logger: Optional[logging.Logger] = None) -> Optional[Dict[str, Any]]:
        """
        Handle event inputs for AWS Lex connector.

        Args:
            conversation_id: Unique identifier for the conversation
            message_data: Message data containing the event
            logger: Optional logger instance

        Returns:
            Response that enables appropriate input mode, or None if no response is needed
        """
        if logger and "event_data" in message_data:
            event_type = message_data.get("event_data", {}).get("event_type")
            event_name = message_data.get("event_data", {}).get("name", "")
            logger.info(f"Event for conversation {conversation_id}: event_type={event_type}, name={event_name}")

        # Handle START_OF_DTMF event specifically
        if message_data.get("event_data", {}).get("event_type") == 4:  # START_OF_DTMF
            logger.info(f"Handling START_OF_DTMF event for conversation {conversation_id}")
            
            # Add conversation to DTMF mode tracking to disable speech detection
            self.session_manager.add_dtmf_mode_tracking(conversation_id)
            logger.info(f"Added conversation {conversation_id} to DTMF mode tracking - speech detection disabled")
            
            # Return None - START_OF_DTMF event already enables DTMF mode
            # No need for additional START_OF_INPUT event
            logger.info(f"START_OF_DTMF event processed for conversation {conversation_id} - DTMF mode enabled")
            return None

        # For other events, return None (no response needed)
        # Most events don't require a response from the connector
        logger.info(f"Event type {message_data.get('event_data', {}).get('event_type')} for conversation {conversation_id} - returning None")
        return None

    def _handle_dtmf_input(self, conversation_id: str, message_data: Dict[str, Any], bot_id: str, session_id: str, bot_name: str) -> Optional[Dict[str, Any]]:
        """
        Handle DTMF input for the Lex bot.

        Args:
            conversation_id: Conversation identifier
            message_data: Message data containing DTMF input
            bot_id: Lex bot ID
            session_id: Lex session ID
            bot_name: Name of the bot

        Returns:
            Response based on DTMF input
        """
        dtmf_data = message_data.get("dtmf_data", {})
        dtmf_events = dtmf_data.get("dtmf_events", [])

        if dtmf_events:
            self.logger.info(f"Received DTMF input for conversation {conversation_id}: {dtmf_events}")
            # Convert DTMF events to a string
            dtmf_string = "".join([str(digit) for digit in dtmf_events])

            # Remove conversation from DTMF mode tracking to re-enable speech detection
            self.session_manager.remove_dtmf_mode_tracking(conversation_id)
            self.logger.info(f"Removed conversation {conversation_id} from DTMF mode tracking - speech detection re-enabled")

            # Send all DTMF digits directly to AWS Lex
            self.logger.debug(f"Sending DTMF {dtmf_string} to Lex for conversation {conversation_id}")
            # Send clean DTMF digits to Lex for better intent matching
            text_input = dtmf_string
            return self._send_text_to_lex(conversation_id, text_input)

        # If no DTMF events, return None (no response needed)
        self.logger.debug(f"No DTMF events received for conversation {conversation_id}, returning None")
        return None

    def _handle_audio_input(self, conversation_id: str, message_data: Dict[str, Any],
                          bot_id: str, session_id: str, bot_name: str) -> Iterator[Optional[Dict[str, Any]]]:
        """
        Handle audio input for the Lex bot.

        Args:
            conversation_id: Conversation identifier
            message_data: Message data containing audio input
            bot_id: Lex bot ID
            session_id: Lex session ID
            bot_name: Name of the bot

        Returns:
            Iterator yielding responses from Lex with processed audio.
            Yields None when no response is needed (e.g., waiting for speech).
        """
        try:
            # Check if conversation is in DTMF mode - if so, skip speech detection entirely
            if self.session_manager.has_dtmf_mode_tracking(conversation_id):
                self.logger.debug(f"Conversation {conversation_id} is in DTMF mode, skipping speech detection")
                return

            # Extract audio data from the message
            audio_bytes = self.extract_audio_data(message_data.get("audio_data"), conversation_id, self.logger)

            if not audio_bytes:
                self.logger.error(f"No valid audio data found for conversation {conversation_id}")
                return

            # Process audio for buffering to detect speech
            buffer_status = self.audio_processor.process_audio_for_buffering(audio_bytes, conversation_id, self.extract_audio_data)
            
            # Check if START_OF_INPUT event has been sent, if not send it only when speech is detected
            if not self.session_manager.has_start_of_input_tracking(conversation_id):
                # Only send START_OF_INPUT when speech is actually detected, not just any audio
                if buffer_status.get('speech_detected', False):
                    self.logger.debug(f"Speech detected, sending START_OF_INPUT event for conversation {conversation_id}")
                    self.session_manager.add_start_of_input_tracking(conversation_id)
                    
                    yield self.create_start_of_input_response(conversation_id)
                    return  # Return after sending START_OF_INPUT event
                else:
                    # Still waiting for speech, yield None (no response needed)
                    self.logger.debug(f"Still waiting for speech in conversation {conversation_id}, yielding None")
                    yield None
                    return

            # Check if silence threshold was detected, if so send END_OF_INPUT event
            # This applies to both first and subsequent audio segments
            if buffer_status.get('silence_detected', False):
                self.logger.debug("Silence threshold detected, sending END_OF_INPUT event for next audio input cycle")
                yield self.create_end_of_input_response(conversation_id)

                # Send buffered audio to AWS Lex
                yield from self._send_audio_to_lex(conversation_id)

                return

        except Exception as e:
            self.error_handler.handle_audio_processing_error(e, conversation_id)

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
            if not self.session_manager.has_session(conversation_id):
                self.logger.error(f"No session found for conversation {conversation_id}")
                return self.error_handler.create_session_error_response(conversation_id, ErrorContext.SESSION_NO_SESSION)
            
            self.logger.debug(f"Sending text '{text_input}' to Lex for conversation {conversation_id}")

            # Get session details
            bot_id = self.session_manager.get_bot_id(conversation_id)
            session_id = self.session_manager.get_session_id(conversation_id)
            
            # Log session details for debugging
            self.logger.debug(f"Session details for conversation {conversation_id}: bot_id={bot_id}, session_id={session_id}")
            
            # Validate session details
            if not session_id:
                self.logger.error(f"No session ID found for conversation {conversation_id}")
                return self.error_handler.create_session_error_response(conversation_id, ErrorContext.SESSION_NO_SESSION)
            if not bot_id:
                self.logger.error(f"No bot ID found for conversation {conversation_id}")
                return self.error_handler.create_session_error_response(conversation_id, ErrorContext.SESSION_NO_SESSION)

            # Send text to AWS Lex using recognize_utterance
            try:
                # Convert text to bytes for the request
                text_bytes = text_input.encode('utf-8')
                
                self.logger.debug(f"Sending text to AWS Lex: botId={bot_id}, botAliasId={self.bot_alias_id}, localeId={self.locale_id}, sessionId={session_id}, text='{text_input}'")

                response = self.lex_runtime.recognize_utterance(
                    botId=bot_id,
                    botAliasId=self.bot_alias_id,
                    localeId=self.locale_id,
                    sessionId=session_id,
                    requestContentType=self.text_request_content_type,
                    responseContentType=self.response_content_type,
                    inputStream=text_bytes
                )

                self.logger.debug(f"Received response from AWS Lex for conversation {conversation_id}")
                
                # Process the Lex response using the comprehensive response handler method
                messages_data = self.response_handler._decode_lex_response('messages', response) or []
                
                # Use the official response handler method
                for response_dict in self.response_handler.process_lex_response(
                    conversation_id=conversation_id,
                    response=response,
                    messages_data=messages_data,
                    audio_processor=self.audio_processor,
                    session_manager=self.session_manager
                ):
                    return response_dict  # Return the first (and typically only) response

            except ClientError as e:
                self.error_handler.handle_lex_api_error(e, conversation_id, ErrorContext.LEX_TEXT_PROCESSING)
                return self.error_handler.create_error_response(
                    conversation_id=conversation_id,
                    error_message="An error occurred while processing your input with AWS Lex. Please try again.",
                    context=ErrorContext.LEX_TEXT_PROCESSING
                )

        except Exception as e:
            self.error_handler.handle_text_processing_error(e, conversation_id, text_input)
            return self.error_handler.create_error_response(
                conversation_id=conversation_id,
                error_message="An error occurred while processing your text. Please try again.",
                context=ErrorContext.TEXT_PROCESSING
            )


    def _send_audio_to_lex(self, conversation_id: str) -> Iterator[Dict[str, Any]]:
        """
        Send buffered audio to AWS Lex and process the response.

        Args:
            conversation_id: Conversation identifier

        Yields:
            Responses from Lex containing audio and text
        """
        try:
            # Get session info
            if not self.session_manager.has_session(conversation_id):
                self.logger.error(f"No session found for conversation {conversation_id}")
                return

            # Get the audio buffer for this conversation
            if not self.audio_processor.has_audio_buffer(conversation_id):
                self.logger.error(f"No audio buffer found for conversation {conversation_id}")
                return

            buffered_audio = self.audio_processor.get_buffered_audio(conversation_id)

            if not buffered_audio:
                self.logger.warning(f"No audio data in buffer for conversation {conversation_id}")
                return

            self.logger.debug(f"Processing {len(buffered_audio)} bytes of audio for conversation {conversation_id}")

            # Log the buffered audio that gets sent to AWS Lex (this is what actually matters for debugging)
            self.audio_processor.log_wxcc_audio(conversation_id, buffered_audio)

            # Extract session details
            bot_id = self.session_manager.get_bot_id(conversation_id)
            session_id = self.session_manager.get_session_id(conversation_id)
            
            # Log session details for debugging
            self.logger.debug(f"Session details for conversation {conversation_id}: bot_id={bot_id}, session_id={session_id}")
            
            # Validate session details
            if not session_id:
                self.logger.error(f"No session ID found for conversation {conversation_id}")
                return
            if not bot_id:
                self.logger.error(f"No bot ID found for conversation {conversation_id}")
                return

            # Send audio to AWS Lex
            try:
                # Convert WxCC u-law audio to 16-bit PCM at 16kHz for AWS Lex
                pcm_audio = self.audio_processor.convert_wxcc_audio_to_lex_format(buffered_audio)
                
                self.logger.debug(f"Converted {len(buffered_audio)} bytes u-law to {len(pcm_audio)} bytes 16-bit PCM at 16kHz")

                # Log the parameters being sent to AWS Lex for debugging
                self.logger.debug(f"Sending to AWS Lex: botId={bot_id}, botAliasId={self.bot_alias_id}, localeId={self.locale_id}, sessionId={session_id}")

                response = self.lex_runtime.recognize_utterance(
                    botId=bot_id,
                    botAliasId=self.bot_alias_id,
                    localeId=self.locale_id,
                    sessionId=session_id,
                    requestContentType=self.audio_request_content_type,  # 16-bit PCM, 16kHz, little-endian
                    responseContentType=self.response_content_type,
                    inputStream=pcm_audio
                )

                self.logger.debug(f"Lex API response received for audio input: {type(response)}")

                # Log decoded input transcript and messages for debugging
                input_transcript_data = self.response_handler._decode_lex_response('inputTranscript', response)
                if input_transcript_data is None:
                    self.logger.warning("No input transcript generated - audio may have quality issues")

                messages_data = self.response_handler._decode_lex_response('messages', response)
                if messages_data is None:
                    self.logger.debug("No messages in response")

                # Log key Lex V2 response fields for conversation state monitoring
                interpretations_data = self.response_handler._decode_lex_response('interpretations', response)
                if interpretations_data is None:
                    self.logger.debug("No interpretations in response")
                else:
                    # Consolidate interpretation logging into a single INFO log with summary
                    interpretation_summary = []
                    primary_intent_state = None
                    primary_intent_name = None
                    
                    for interpretation in interpretations_data:
                        intent = interpretation.get('intent', {})
                        intent_name = intent.get('name', 'unknown')
                        intent_state = intent.get('state', 'unknown')
                        confidence = interpretation.get('nluConfidence', {}).get('score', 'unknown')
                        interpretation_summary.append(f"{intent_name}({intent_state}, conf:{confidence})")
                        
                        # Track the primary interpretation (first one)
                        if primary_intent_state is None:
                            primary_intent_state = intent_state
                            primary_intent_name = intent_name
                    
                    self.logger.info(f"Lex response: {len(interpretations_data)} interpretation(s) - {', '.join(interpretation_summary)}")
                    self.logger.debug(f"Full interpretation details: {interpretations_data}")
                    
                    # Check if primary intent indicates conversation completion or failure
                    if primary_intent_state == 'Fulfilled':
                        self.logger.info(f"Primary intent '{primary_intent_name}' is fulfilled - conversation complete")
                        # Create a SESSION_END response for fulfilled intent
                        session_end_response = self.response_handler.create_session_end_response(
                            conversation_id=conversation_id,
                            bot_name=self.session_manager.get_bot_name(conversation_id) or "unknown",
                            intent_name=primary_intent_name
                        )
                        
                        # Reset audio buffer and conversation state
                        self.audio_processor.reset_audio_buffer(conversation_id)
                        self.session_manager.reset_conversation_for_next_input(conversation_id)
                        yield session_end_response
                        return
                        
                    elif primary_intent_state == 'ReadyForFulfillment':
                        self.logger.info(f"Primary intent '{primary_intent_name}' - escalation needed")
                        # Create a TRANSFER_TO_AGENT response
                        transfer_response = self.response_handler.create_transfer_response(
                            conversation_id=conversation_id,
                            bot_name=self.session_manager.get_bot_name(conversation_id) or "unknown",
                            intent_name=primary_intent_name
                        )
                        
                        # Reset audio buffer and conversation state
                        self.audio_processor.reset_audio_buffer(conversation_id)
                        self.session_manager.reset_conversation_for_next_input(conversation_id)
                        yield transfer_response
                        return

                # Check session state and dialog actions BEFORE audio processing
                session_state_data = self.response_handler._decode_lex_response('sessionState', response)
                if session_state_data is None:
                    self.logger.debug("No session state in response")
                else:
                    # Extract key session state info for INFO level logging
                    dialog_action = session_state_data.get('dialogAction', {})
                    action_type = dialog_action.get('type', 'unknown') if dialog_action else 'none'
                    
                    # Log active contexts count
                    active_contexts = session_state_data.get('activeContexts', [])
                    
                    # Provide summary at INFO level, full details at DEBUG level
                    self.logger.info(f"Session state: dialog_action={action_type}, contexts={len(active_contexts)}")
                    self.logger.debug(f"Full session state: {session_state_data}")
                    
                    # Log individual context names at DEBUG level
                    if active_contexts:
                        for context in active_contexts:
                            context_name = context.get('name', 'unknown')
                            self.logger.debug(f"  Context: {context_name}")

                    # Check if Lex is closing the conversation and handle accordingly
                    if action_type == 'Close':
                        self.logger.info(f"Lex dialog action is 'Close' - ending conversation {conversation_id}")
                        
                        # Create a SESSION_END response
                        session_end_response = self.response_handler.create_lex_dialog_close_response(
                            conversation_id=conversation_id,
                            bot_name=self.session_manager.get_bot_name(conversation_id) or "unknown"
                        )
                        
                        # Reset audio buffer and conversation state
                        self.audio_processor.reset_audio_buffer(conversation_id)
                        self.session_manager.reset_conversation_for_next_input(conversation_id)
                        yield session_end_response
                        return

                # Process the Lex response using the comprehensive response handler method
                messages_data = self.response_handler._decode_lex_response('messages', response) or []
                
                # Use the official response handler method - it handles buffer reset and session management internally
                yield from self.response_handler.process_lex_response(
                    conversation_id=conversation_id,
                    response=response,
                    messages_data=messages_data,
                    audio_processor=self.audio_processor,
                    session_manager=self.session_manager
                )

            except ClientError as e:
                self.error_handler.handle_lex_api_error(e, conversation_id, ErrorContext.LEX_AUDIO_PROCESSING)
                
                # Reset buffer and log the error
                self.audio_processor.reset_audio_buffer(conversation_id)
                # Reset conversation state for next audio input cycle
                self.session_manager.reset_conversation_for_next_input(conversation_id)
                self.logger.debug("Audio processing failed due to Lex API error, buffer reset")

            except Exception as e:
                self.error_handler.handle_audio_processing_error(e, conversation_id)
                
                # Reset buffer and log the error
                self.audio_processor.reset_audio_buffer(conversation_id)
                # Reset conversation state for next audio input cycle
                self.session_manager.reset_conversation_for_next_input(conversation_id)
                self.logger.debug("Audio processing failed due to unexpected error, buffer reset")

        except Exception as e:
            self.error_handler.handle_audio_processing_error(e, conversation_id)
            self.logger.debug("Audio processing failed, no response generated")



    def end_conversation(self, conversation_id: str, message_data: Dict[str, Any] = None) -> None:
        """
        End an active conversation and clean up resources.

        Args:
            conversation_id: Active conversation identifier
            message_data: Optional final message data
        """
        # Log conversation details first, in case there's an error in cleanup
        self.logger.info(f"Ending AWS Lex conversation: {conversation_id}")

        # End session using session manager (this may warn if session doesn't exist, which is OK)
        session_info = self.session_manager.end_session(conversation_id, message_data)
        
        if session_info:
            self.logger.debug(f"Successfully ended session for conversation {conversation_id}")
        else:
            self.logger.debug(f"No active session found for conversation {conversation_id} (this is normal for early termination)")

        # Always clean up audio resources, regardless of session state
        self.audio_processor.cleanup_audio_buffer(conversation_id)
        self.audio_processor.cleanup_audio_logging(conversation_id)

        self.logger.info(f"Completed cleanup for AWS Lex conversation: {conversation_id}")

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
        self.session_manager.refresh_bot_cache()
        self.get_available_agents()






