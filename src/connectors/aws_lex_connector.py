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
        self.request_content_type = self.config_manager.get_request_content_type()
        self.response_content_type = self.config_manager.get_response_content_type()
        self.aws_credentials = self.config_manager.get_aws_credentials()

        # Initialize AWS clients
        self._init_aws_clients()

        # Initialize session manager
        self.session_manager = AWSLexSessionManager(self.logger)
        
        # Initialize response handler
        self.response_handler = AWSLexResponseHandler(self.logger)

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
            self.logger.error(f"Failed to initialize AWS clients: {e}")
            raise

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
                # Convert text to bytes for the reques
                text_input = "I need to book a hotel room"
                text_bytes = text_input.encode('utf-8')

                self.logger.debug(f"Sending initial text to Lex: '{text_input}'")

                response = self.lex_runtime.recognize_utterance(
                    botId=actual_bot_id,
                    botAliasId=self.bot_alias_id,
                    localeId=self.locale_id,
                    sessionId=session_id,
                    requestContentType=self.request_content_type,
                    responseContentType=self.response_content_type,
                    inputStream=text_bytes
                )

                self.logger.debug(f"Lex API response received: {type(response)}")
                self.logger.debug(f"Lex API response keys: {list(response.keys()) if hasattr(response, 'keys') else 'No keys'}")

                # Extract audio response
                audio_stream = response.get('audioStream')
                if audio_stream:
                    self.logger.debug(f"Audio stream found: {type(audio_stream)}")
                    audio_response = audio_stream.read()
                    audio_stream.close()
                    self.logger.info(f"Received audio response: {len(audio_response)} bytes")

                    if audio_response:
                        # Log outgoing AWS Lex audio if audio logging is enabled
                        self.audio_processor.log_aws_audio(conversation_id, audio_response)
                        
                        self.logger.debug("Audio content is valid, returning response with audio")

                        # Use the audio processor to convert AWS Lex audio to WxCC-compatible format
                        # AWS Lex returns 16kHz, 16-bit PCM, but WxCC expects 8kHz, 8-bit u-law
                        wav_audio, content_type = self.audio_processor.convert_lex_audio_to_wxcc_format(
                            audio_response
                        )

                        return self.create_response(
                            conversation_id=conversation_id,
                            message_type="welcome",
                            text=f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                            audio_content=wav_audio,
                            barge_in_enabled=False,
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
                        self.logger.debug(f"Lex messages: {response.messages}")
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
                    barge_in_enabled=False,
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
                    barge_in_enabled=False,
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

    def send_message(self, conversation_id: str, message_data: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
        """
        Send a message to the AWS Lex bot and get a response.

        Args:
            conversation_id: Active conversation identifier
            message_data: Message data containing input (audio or text)

        Returns:
            Iterator yielding responses from Lex containing audio and text
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
            yield self.create_response(
                conversation_id=conversation_id,
                message_type="error",
                text="No active conversation found. Please start a new conversation.",
                audio_content=b"",
                barge_in_enabled=False,
                response_type="final"
            )
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
        yield self.handle_unrecognized_input(conversation_id, message_data, self.logger)

    def _handle_dtmf_input(self, conversation_id: str, message_data: Dict[str, Any], bot_id: str, session_id: str, bot_name: str) -> Dict[str, Any]:
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

            # Process special DTMF codes
            if "5" in dtmf_string:  # Transfer code
                self.logger.info(f"DTMF transfer requested for conversation {conversation_id}")
                # Reset conversation state for next audio input cycle
                self.session_manager.reset_conversation_for_next_input(conversation_id)
                return self.create_transfer_response(
                    conversation_id=conversation_id,
                    text=f"Transferring you from the {bot_name} assistant to a live agent.",
                    audio_content=b"",  # Would need to load transfer audio here
                    reason="dtmf_transfer_requested"
                )
            elif "6" in dtmf_string:  # Goodbye code
                self.logger.info(f"DTMF goodbye requested for conversation {conversation_id}")
                # Reset conversation state for next audio input cycle
                self.session_manager.reset_conversation_for_next_input(conversation_id)
                return self.create_goodbye_response(
                    conversation_id=conversation_id,
                    text=f"Goodbye from the {bot_name} assistant. Thank you for your time.",
                    audio_content=b"",  # Would need to load transfer audio here
                    reason="dtmf_goodbye_requested"
                )
            else:
                # For other DTMF digits, send to Lex as tex
                self.logger.debug(f"Sending DTMF {dtmf_string} to Lex for conversation {conversation_id}")
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
                          bot_id: str, session_id: str, bot_name: str) -> Iterator[Dict[str, Any]]:
        """
        Handle audio input for the Lex bot.

        Args:
            conversation_id: Conversation identifier
            message_data: Message data containing audio input
            bot_id: Lex bot ID
            session_id: Lex session ID
            bot_name: Name of the bot

        Returns:
            Response from Lex with processed audio
        """
        try:
            # Extract audio data from the message
            audio_bytes = self.extract_audio_data(message_data.get("audio_data"), conversation_id, self.logger)

            # Check if START_OF_INPUT event has been sent, if not send it
            if not self.session_manager.has_start_of_input_tracking(conversation_id):
                self.logger.debug(f"Sending START_OF_INPUT event for conversation {conversation_id}")
                self.session_manager.add_start_of_input_tracking(conversation_id)
                
                yield self.create_start_of_input_response(conversation_id)
                return  # Return after sending START_OF_INPUT event
            
            if not audio_bytes:
                self.logger.error(f"No valid audio data found for conversation {conversation_id}")
                return

            # Buffer audio (always enabled for AWS Lex connector)
            silence_detected = self.audio_processor.process_audio_for_buffering(audio_bytes, conversation_id, self.extract_audio_data)

            # Check if silence threshold was detected, if so send END_OF_INPUT event
            if silence_detected:
                self.logger.debug(f"Silence threshold detected, sending END_OF_INPUT event for next audio input cycle")
                yield self.create_end_of_input_response(conversation_id)

                # Send buffered audio to AWS Lex
                yield from self._send_audio_to_lex(conversation_id)

                return

        except Exception as e:
            self.logger.error(f"Error processing audio input: {e}")

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
                return self.create_response(
                    conversation_id=conversation_id,
                    message_type="error",
                    text="I couldn't process your request. Please try again.",
                    barge_in_enabled=False,
                    response_type="final"
                )
            
            self.logger.debug(f"Sending text '{text_input}' to Lex for conversation {conversation_id}")

            # This is a placeholder for the actual Lex text implementation
            self.logger.debug(f"Text functionality not yet fully implemented: {text_input}")
            # Reset conversation state for next audio input cycle
            self.session_manager.reset_conversation_for_next_input(conversation_id)
            # Return a placeholder response until full implementation is complete
            return self.create_response(
                conversation_id=conversation_id,
                message_type="silence",
                text=f"Processing text input: {text_input}",
                barge_in_enabled=False,
                response_type="final"
            )
        except Exception as e:
            self.logger.error(f"Error processing text input: {e}")
            # Reset conversation state for next audio input cycle
            self.session_manager.reset_conversation_for_next_input(conversation_id)
            return self.create_response(
                conversation_id=conversation_id,
                message_type="error",
                text="An error occurred while processing your text. Please try again.",
                barge_in_enabled=False,
                response_type="final"
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

            # Send audio to AWS Lex
            try:
                # Convert WxCC u-law audio to 16-bit PCM at 16kHz for AWS Lex
                pcm_audio = self.audio_processor.convert_wxcc_audio_to_lex_format(buffered_audio)
                
                self.logger.debug(f"Converted {len(buffered_audio)} bytes u-law to {len(pcm_audio)} bytes 16-bit PCM at 16kHz")

                response = self.lex_runtime.recognize_utterance(
                    botId=bot_id,
                    botAliasId=self.bot_alias_id,
                    localeId=self.locale_id,
                    requestContentType='audio/l16; rate=16000; channels=1',  # 16-bit PCM, 16kHz, little-endian
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
                        
                    elif primary_intent_state == 'Failed':
                        self.logger.info(f"Primary intent '{primary_intent_name}' failed - escalation needed")
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

                # Extract audio response
                audio_stream = response.get('audioStream')
                if audio_stream:
                    self.logger.debug(f"Audio stream found: {type(audio_stream)}")
                    audio_response = audio_stream.read()
                    audio_stream.close()
                    self.logger.info(f"Received audio response: {len(audio_response)} bytes")

                    if audio_response:
                        # Log outgoing AWS Lex audio if audio logging is enabled
                        self.audio_processor.log_aws_audio(conversation_id, audio_response)
                        
                        self.logger.debug("Audio content is valid, processing Lex response")

                        # Convert AWS Lex audio to WxCC-compatible format
                        wav_audio, content_type = self.audio_processor.convert_lex_audio_to_wxcc_format(
                            audio_response
                        )

                        # Extract text from response if available
                        text_response = "I heard your audio input and processed it."
                        if messages_data and len(messages_data) > 0:
                            first_message = messages_data[0]
                            if 'content' in first_message:
                                text_response = first_message['content']
                                self.logger.debug(f"Extracted text response: {text_response}")
                        else:
                            self.logger.debug("No text content found in messages, using generic response")

                        # Reset the buffer after successful processing
                        self.audio_processor.reset_audio_buffer(conversation_id)

                        # Yield the Lex response
                        response_dict = self.response_handler.create_audio_response(
                            conversation_id=conversation_id,
                            text_response=text_response,
                            audio_content=wav_audio,
                            content_type=content_type
                        )
                        
                        # Reset conversation state for next audio input cycle
                        self.session_manager.reset_conversation_for_next_input(conversation_id)
                        
                        yield response_dict
                else:
                    self.logger.error("No audio stream in Lex response")
                    # Reset buffer and log the issue
                    self.audio_processor.reset_audio_buffer(conversation_id)
                    # Reset conversation state for next audio input cycle
                    self.session_manager.reset_conversation_for_next_input(conversation_id)
                    self.logger.debug("Audio processing completed but no response generated")

            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_message = e.response['Error']['Message']
                self.logger.error(f"Lex API error during audio processing: {error_code} - {error_message}")
                
                # Reset buffer and log the error
                self.audio_processor.reset_audio_buffer(conversation_id)
                # Reset conversation state for next audio input cycle
                self.session_manager.reset_conversation_for_next_input(conversation_id)
                self.logger.debug("Audio processing failed due to Lex API error, buffer reset")

            except Exception as e:
                self.logger.error(f"Unexpected error during audio processing: {e}")
                import traceback
                self.logger.error(f"Traceback: {traceback.format_exc()}")
                
                # Reset buffer and log the error
                self.audio_processor.reset_audio_buffer(conversation_id)
                # Reset conversation state for next audio input cycle
                self.session_manager.reset_conversation_for_next_input(conversation_id)
                self.logger.debug("Audio processing failed due to unexpected error, buffer reset")

        except Exception as e:
            self.logger.error(f"Error in _send_audio_to_lex: {e}")
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

        # End session using session manager
        session_info = self.session_manager.end_session(conversation_id, message_data)

        # Finalize audio buffering (always enabled for AWS Lex connector)
        self.audio_processor.cleanup_audio_buffer(conversation_id)

        # Clean up audio logging resources
        self.audio_processor.cleanup_audio_logging(conversation_id)

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






