"""
AWS Lex Response Handler for Webex Contact Center BYOVA Gateway.

This module handles all response-related operations for the AWS Lex connector,
including response creation, event generation, and response processing logic.
"""

import logging
from typing import Any, Dict, List, Optional, Generator

from botocore.exceptions import ClientError
from .aws_lex_error_handler import AWSLexErrorHandler, ErrorContext


class AWSLexResponseHandler:
    """
    Handles all response-related operations for AWS Lex connector.
    
    This class encapsulates response creation, event generation, and response
    processing logic to keep the main connector focused on business logic.
    """

    def __init__(self, logger: logging.Logger, error_handler: Optional[AWSLexErrorHandler] = None, barge_in_enabled: bool = False):
        """
        Initialize the response handler.

        Args:
            logger: Logger instance for the connector
            error_handler: Optional error handler instance
            barge_in_enabled: Whether barge-in is enabled for responses
        """
        self.logger = logger
        self.error_handler = error_handler or AWSLexErrorHandler(logger)
        self.barge_in_enabled = barge_in_enabled

    def create_session_end_response(self, conversation_id: str, bot_name: str, 
                                  reason: str = "intent_fulfilled", 
                                  intent_name: str = "unknown") -> Dict[str, Any]:
        """
        Create a session end response with SESSION_END event.

        Args:
            conversation_id: Conversation identifier
            bot_name: Name of the bot
            reason: Reason for session end
            intent_name: Name of the intent that was fulfilled

        Returns:
            Session end response dictionary
        """
        response = {
            "conversation_id": conversation_id,
            "message_type": "session_end",
            "text": "I've successfully completed your request. Thank you for calling!",
            "audio_content": b"",
            "barge_in_enabled": False,
            "response_type": "final"
        }
        
        # Add SESSION_END output event
        response["output_events"] = [{
            "event_type": "SESSION_END",
            "name": "lex_intent_fulfilled",
            "metadata": {
                "reason": reason,
                "intent_name": intent_name,
                "bot_name": bot_name,
                "conversation_id": conversation_id
            }
        }]
        
        return response

    def create_transfer_response(self, conversation_id: str, bot_name: str,
                               intent_name: str = "unknown") -> Dict[str, Any]:
        """
        Create a transfer response with TRANSFER_TO_AGENT event.

        Args:
            conversation_id: Conversation identifier
            bot_name: Name of the bot
            intent_name: Name of the intent that failed

        Returns:
            Transfer response dictionary
        """
        response = {
            "conversation_id": conversation_id,
            "message_type": "transfer",
            "text": "I'm having trouble with your request. Let me transfer you to a human agent.",
            "audio_content": b"",
            "barge_in_enabled": False,
            "response_type": "final"
        }
        
        # Add TRANSFER_TO_AGENT output event
        response["output_events"] = [{
            "event_type": "TRANSFER_TO_AGENT",
            "name": "lex_intent_failed",
            "metadata": {
                "reason": "intent_failed",
                "intent_name": intent_name,
                "bot_name": bot_name,
                "conversation_id": conversation_id
            }
        }]
        
        return response

    def create_lex_dialog_close_response(self, conversation_id: str, bot_name: str) -> Dict[str, Any]:
        """
        Create a session end response when Lex dialog action is 'Close'.

        Args:
            conversation_id: Conversation identifier
            bot_name: Name of the bot

        Returns:
            Session end response dictionary
        """
        response = {
            "conversation_id": conversation_id,
            "message_type": "session_end",
            "text": "Thank you for calling. Have a great day!",
            "audio_content": b"",  # No audio for session end
            "barge_in_enabled": False,
            "response_type": "final"
        }
        
        # Add SESSION_END output event
        response["output_events"] = [{
            "event_type": "SESSION_END",
            "name": "lex_conversation_ended",
            "metadata": {
                "reason": "lex_dialog_closed",
                "bot_name": bot_name,
                "conversation_id": conversation_id
            }
        }]
        
        return response

    def create_audio_response(self, conversation_id: str, text_response: str,
                            audio_content: bytes, content_type: str = "audio/wav",
                            barge_in_enabled: bool = False) -> Dict[str, Any]:
        """
        Create a standard audio response with DTMF input mode enabled.

        Args:
            conversation_id: Conversation identifier
            text_response: Text content of the response
            audio_content: Audio content in bytes
            content_type: MIME type of the audio content
            barge_in_enabled: Whether barge-in is enabled for this response

        Returns:
            Audio response dictionary with DTMF input mode enabled
        """
        response = {
            "conversation_id": conversation_id,
            "message_type": "response",
            "text": text_response,
            "audio_content": audio_content,
            "barge_in_enabled": barge_in_enabled,
            "content_type": content_type,
            "response_type": "final",
            "input_mode": 3,  # INPUT_VOICE_DTMF = 3 (from protobuf)
            "input_handling_config": {
                "dtmf_config": {
                    "inter_digit_timeout_msec": 5000,  # 5 second timeout between digits
                    "dtmf_input_length": 10  # Allow up to 10 digits
                }
            }
        }
        
        return response

    def process_lex_response(self, conversation_id: str, response: Dict[str, Any],
                           messages_data: Optional[List[Dict[str, Any]]],
                           audio_processor, session_manager) -> Generator[Dict[str, Any], None, None]:
        """
        Process a Lex response and generate appropriate WxCC responses.

        Args:
            conversation_id: Conversation identifier
            response: Raw Lex response
            messages_data: Decoded messages from Lex
            audio_processor: Audio processor instance
            session_manager: Session manager instance

        Yields:
            WxCC response dictionaries
        """
        try:
            # Check for intent interpretations first
            interpretations_data = self._decode_lex_response('interpretations', response)
            if interpretations_data and len(interpretations_data) > 0:
                primary_intent = interpretations_data[0]
                primary_intent_name = primary_intent.get('intent', {}).get('name', 'unknown')
                primary_intent_state = primary_intent.get('intent', {}).get('state', 'unknown')
                
                self.logger.debug(f"Primary intent: {primary_intent_name}, state: {primary_intent_state}")
                
                # Handle intent fulfillment
                if primary_intent_state == 'Fulfilled':
                    self.logger.info(f"Primary intent '{primary_intent_name}' fulfilled - ending conversation")
                    
                    session_end_response = self.create_session_end_response(
                        conversation_id=conversation_id,
                        bot_name=session_manager.get_bot_name(conversation_id) or "unknown",
                        intent_name=primary_intent_name
                    )
                    
                    # Reset audio buffer and conversation state
                    audio_processor.reset_audio_buffer(conversation_id)
                    session_manager.reset_conversation_for_next_input(conversation_id)
                    yield session_end_response
                    return
                    
                elif primary_intent_state == 'Failed':
                    self.logger.info(f"Primary intent '{primary_intent_name}' failed - escalation needed")
                    
                    transfer_response = self.create_transfer_response(
                        conversation_id=conversation_id,
                        bot_name=session_manager.get_bot_name(conversation_id) or "unknown",
                        intent_name=primary_intent_name
                    )
                    
                    # Reset audio buffer and conversation state
                    audio_processor.reset_audio_buffer(conversation_id)
                    session_manager.reset_conversation_for_next_input(conversation_id)
                    yield transfer_response
                    return

            # Check session state and dialog actions BEFORE audio processing
            session_state_data = self._decode_lex_response('sessionState', response)
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
                    
                    session_end_response = self.create_lex_dialog_close_response(
                        conversation_id=conversation_id,
                        bot_name=session_manager.get_bot_name(conversation_id) or "unknown"
                    )
                    
                    # Reset audio buffer and conversation state
                    audio_processor.reset_audio_buffer(conversation_id)
                    session_manager.reset_conversation_for_next_input(conversation_id)
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
                    audio_processor.log_aws_audio(conversation_id, audio_response)
                    
                    self.logger.debug("Audio content is valid, processing Lex response")

                    # Convert AWS Lex audio to WxCC-compatible format
                    wav_audio, content_type = audio_processor.convert_lex_audio_to_wxcc_format(
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
                    audio_processor.reset_audio_buffer(conversation_id)

                    # Yield the Lex response
                    response_dict = self.create_audio_response(
                        conversation_id=conversation_id,
                        text_response=text_response,
                        audio_content=wav_audio,
                        content_type=content_type,
                        barge_in_enabled=self.barge_in_enabled
                    )
                    
                    # Reset conversation state for next audio input cycle
                    session_manager.reset_conversation_for_next_input(conversation_id)
                    
                    yield response_dict
                else:
                    self.logger.warning("Audio stream was empty from Lex")
                    # Reset buffer and log the issue
                    audio_processor.reset_audio_buffer(conversation_id)
                    # Reset conversation state for next audio input cycle
                    session_manager.reset_conversation_for_next_input(conversation_id)
                    self.logger.debug("Audio processing completed but no response generated")
            else:
                self.logger.debug("No audio stream in Lex response, creating text-only response")
                
                # Extract text from response if available
                text_response = "I processed your input."
                if messages_data and len(messages_data) > 0:
                    first_message = messages_data[0]
                    if isinstance(first_message, dict) and 'content' in first_message:
                        text_response = first_message['content']
                        self.logger.debug(f"Extracted text response: {text_response}")
                
                # Create text-only response
                from .i_vendor_connector import IVendorConnector
                response_dict = {
                    "conversation_id": conversation_id,
                    "message_type": "response",
                    "text": text_response,
                    "audio_content": b"",
                    "barge_in_enabled": self.barge_in_enabled,
                    "response_type": "final",
                    "input_mode": 3,  # INPUT_VOICE_DTMF = 3 (from protobuf)
                    "input_handling_config": {
                        "dtmf_config": {
                            "inter_digit_timeout_msec": 5000,  # 5 second timeout between digits
                            "dtmf_input_length": 10  # Allow up to 10 digits
                        }
                    }
                }
                
                # Reset buffer and conversation state
                audio_processor.reset_audio_buffer(conversation_id)
                session_manager.reset_conversation_for_next_input(conversation_id)
                
                yield response_dict

        except ClientError as e:
            self.error_handler.handle_lex_api_error(e, conversation_id, ErrorContext.LEX_AUDIO_PROCESSING)
            
            # Reset buffer and log the error
            audio_processor.reset_audio_buffer(conversation_id)
            # Reset conversation state for next audio input cycle
            session_manager.reset_conversation_for_next_input(conversation_id)
            self.logger.debug("Audio processing failed due to Lex API error, buffer reset")

        except Exception as e:
            self.error_handler.handle_audio_processing_error(e, conversation_id)
            
            # Reset buffer and log the error
            audio_processor.reset_audio_buffer(conversation_id)
            # Reset conversation state for next audio input cycle
            session_manager.reset_conversation_for_next_input(conversation_id)
            self.logger.debug("Audio processing failed due to unexpected error, buffer reset")

    def _decode_lex_response(self, field_name: str, response) -> Any:
        """
        Decode a compressed field from AWS Lex response.

        Args:
            field_name: Name of the field to decode
            response: Raw Lex response

        Returns:
            Decoded field data or None if decoding fails
        """
        try:
            import base64
            import gzip
            import json
            
            # Try to get the field value from both formats
            field_value = None
            if hasattr(response, field_name) and getattr(response, field_name):
                field_value = getattr(response, field_name)
            elif isinstance(response, dict) and response.get(field_name):
                field_value = response[field_name]
            
            if not field_value:
                return None
            
            # Decode the compressed field
            decoded_bytes = base64.b64decode(field_value)
            decompressed = gzip.decompress(decoded_bytes)
            decoded_data = json.loads(decompressed)
            
            self.logger.debug(f"Decoded {field_name}: {decoded_data}")
            return decoded_data
            
        except Exception as e:
            self.error_handler.handle_response_decoding_error(e, field_name, field_value)
            return None
