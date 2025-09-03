"""
AWS Lex Error Handler for Webex Contact Center BYOVA Gateway.

This module handles all error-related operations for the AWS Lex connector,
including error logging, error response generation, and error recovery logic.
"""

import logging
import traceback
from enum import Enum
from typing import Any, Dict, Optional

from botocore.exceptions import ClientError


class ErrorContext(Enum):
    """Enumeration of error contexts for consistent error handling."""
    
    # AWS and Lex API contexts
    AWS_CLIENT_INIT = "aws_client_initialization"
    LEX_API_CALL = "lex_api_call"
    LEX_AUDIO_PROCESSING = "lex_audio_processing"
    
    # Audio processing contexts
    AUDIO_PROCESSING = "audio_processing"
    AUDIO_CONVERSION = "audio_conversion"
    AUDIO_BUFFER_OPERATION = "audio_buffer_operation"
    
    # Session and conversation contexts
    CONVERSATION_START = "conversation_start"
    CONVERSATION_GENERAL = "conversation"
    SESSION_MANAGEMENT = "session_management"
    SESSION_NO_SESSION = "session_no_session"
    SESSION_EXPIRED = "session_expired"
    SESSION_INVALID = "session_invalid"
    
    # Input processing contexts
    TEXT_PROCESSING = "text_processing"
    DTMF_PROCESSING = "dtmf_processing"
    EVENT_PROCESSING = "event_processing"
    
    # Response handling contexts
    RESPONSE_DECODING = "response_decoding"
    RESPONSE_PROCESSING = "response_processing"
    
    # General contexts
    GENERAL = "general"
    NETWORK = "network"
    UNKNOWN = "unknown"


class AWSLexErrorHandler:
    """
    Handles all error-related operations for AWS Lex connector.
    
    This class encapsulates error logging, error response generation, and
    error recovery logic to keep the main connector focused on business logic.
    """

    def __init__(self, logger: logging.Logger):
        """
        Initialize the error handler.

        Args:
            logger: Logger instance for the connector
        """
        self.logger = logger

    def handle_aws_client_init_error(self, error: Exception, context: ErrorContext = ErrorContext.AWS_CLIENT_INIT) -> None:
        """
        Handle AWS client initialization errors.

        Args:
            error: The exception that occurred
            context: Context where the error occurred
        """
        self.logger.error(f"Failed to initialize AWS clients: {error}")
        self.logger.error(f"Context: {context.value}")
        self.logger.error(f"Exception type: {type(error)}")
        self.logger.error(f"Traceback: {traceback.format_exc()}")
        raise error

    def handle_lex_api_error(self, error: ClientError, conversation_id: str, context: ErrorContext = ErrorContext.LEX_API_CALL) -> None:
        """
        Handle AWS Lex API errors.

        Args:
            error: The ClientError from boto3
            conversation_id: Conversation identifier for context
            context: Context where the error occurred
        """
        error_code = error.response['Error']['Code']
        error_message = error.response['Error']['Message']
        
        self.logger.error(f"Lex API error during {context.value}: {error_code} - {error_message}")
        self.logger.error(f"Conversation ID: {conversation_id}")
        self.logger.error(f"Error details: {error.response['Error']}")

    def handle_audio_processing_error(self, error: Exception, conversation_id: str, context: ErrorContext = ErrorContext.AUDIO_PROCESSING) -> None:
        """
        Handle audio processing errors.

        Args:
            error: The exception that occurred
            conversation_id: Conversation identifier for context
            context: Context where the error occurred
        """
        self.logger.error(f"Error during {context.value}: {error}")
        self.logger.error(f"Conversation ID: {conversation_id}")
        self.logger.error(f"Exception type: {type(error)}")
        self.logger.error(f"Traceback: {traceback.format_exc()}")

    def handle_conversation_error(self, error: Exception, conversation_id: str, context: ErrorContext = ErrorContext.CONVERSATION_GENERAL) -> None:
        """
        Handle conversation-related errors.

        Args:
            error: The exception that occurred
            conversation_id: Conversation identifier for context
            context: Context where the error occurred
        """
        self.logger.error(f"Error during {context.value}: {error}")
        self.logger.error(f"Conversation ID: {conversation_id}")
        self.logger.error(f"Exception type: {type(error)}")
        self.logger.error(f"Traceback: {traceback.format_exc()}")

    def handle_text_processing_error(self, error: Exception, conversation_id: str, text_input: str) -> None:
        """
        Handle text processing errors.

        Args:
            error: The exception that occurred
            conversation_id: Conversation identifier for context
            text_input: The text input that caused the error
        """
        self.logger.error(f"Error processing text input: {error}")
        self.logger.error(f"Conversation ID: {conversation_id}")
        self.logger.error(f"Text input: {text_input}")
        self.logger.error(f"Exception type: {type(error)}")
        self.logger.error(f"Traceback: {traceback.format_exc()}")

    def handle_session_error(self, error: Exception, conversation_id: str, context: ErrorContext = ErrorContext.SESSION_MANAGEMENT) -> None:
        """
        Handle session management errors.

        Args:
            error: The exception that occurred
            conversation_id: Conversation identifier for context
            context: Context where the error occurred
        """
        self.logger.error(f"Error during {context.value}: {error}")
        self.logger.error(f"Conversation ID: {conversation_id}")
        self.logger.error(f"Exception type: {type(error)}")
        self.logger.error(f"Traceback: {traceback.format_exc()}")

    def handle_response_decoding_error(self, error: Exception, field_name: str, response_data: Any) -> None:
        """
        Handle response decoding errors.

        Args:
            error: The exception that occurred
            field_name: Name of the field being decoded
            response_data: The response data that caused the error
        """
        self.logger.warning(f"Failed to decode {field_name}: {error}")
        self.logger.debug(f"Raw {field_name} data: {response_data}")
        self.logger.debug(f"Exception type: {type(error)}")

    def handle_audio_conversion_error(self, error: Exception, conversation_id: str, source_format: str, target_format: str) -> None:
        """
        Handle audio conversion errors.

        Args:
            error: The exception that occurred
            conversation_id: Conversation identifier for context
            source_format: Source audio format
            target_format: Target audio format
        """
        self.logger.error(f"Audio conversion error from {source_format} to {target_format}: {error}")
        self.logger.error(f"Conversation ID: {conversation_id}")
        self.logger.error(f"Exception type: {type(error)}")
        self.logger.error(f"Traceback: {traceback.format_exc()}")

    def handle_buffer_operation_error(self, error: Exception, conversation_id: str, operation: str) -> None:
        """
        Handle audio buffer operation errors.

        Args:
            error: The exception that occurred
            conversation_id: Conversation identifier for context
            operation: The buffer operation that failed
        """
        self.logger.error(f"Audio buffer {operation} error: {error}")
        self.logger.error(f"Conversation ID: {conversation_id}")
        self.logger.error(f"Exception type: {type(error)}")
        self.logger.error(f"Traceback: {traceback.format_exc()}")

    def create_error_response(self, conversation_id: str, error_type: str = "error", 
                            error_message: str = "An error occurred. Please try again.",
                            context: ErrorContext = ErrorContext.GENERAL) -> Dict[str, Any]:
        """
        Create a standardized error response.

        Args:
            conversation_id: Conversation identifier
            error_type: Type of error (error, warning, etc.)
            error_message: User-friendly error message
            context: Context where the error occurred

        Returns:
            Standardized error response dictionary
        """
        self.logger.debug(f"Creating error response for conversation {conversation_id}, context: {context.value}")
        
        response = {
            "conversation_id": conversation_id,
            "message_type": error_type,
            "text": error_message,
            "audio_content": b"",
            "barge_in_enabled": False,
            "response_type": "final",
            "error_context": context.value,
            "input_mode": 3,  # INPUT_VOICE_DTMF = 3 (from protobuf)
            "input_handling_config": {
                "dtmf_config": {
                    "inter_digit_timeout_msec": 5000,  # 5 second timeout between digits
                    "dtmf_input_length": 10  # Allow up to 10 digits
                }
            }
        }
        
        return response

    def create_fallback_response(self, conversation_id: str, original_message_type: str = "welcome",
                               fallback_text: str = "I'm having trouble processing your request. Please try again.") -> Dict[str, Any]:
        """
        Create a fallback response when the original response fails.

        Args:
            conversation_id: Conversation identifier
            original_message_type: The original message type that was attempted
            fallback_text: Fallback text to display

        Returns:
            Fallback response dictionary
        """
        self.logger.info(f"Creating fallback response for conversation {conversation_id}, original type: {original_message_type}")
        
        response = {
            "conversation_id": conversation_id,
            "message_type": "error",
            "text": fallback_text,
            "audio_content": b"",
            "barge_in_enabled": False,
            "response_type": "final",
            "fallback_from": original_message_type,
            "input_mode": 3,  # INPUT_VOICE_DTMF = 3 (from protobuf)
            "input_handling_config": {
                "dtmf_config": {
                    "inter_digit_timeout_msec": 5000,  # 5 second timeout between digits
                    "dtmf_input_length": 10  # Allow up to 10 digits
                }
            }
        }
        
        return response

    def create_session_error_response(self, conversation_id: str, error_context: ErrorContext = ErrorContext.SESSION_MANAGEMENT) -> Dict[str, Any]:
        """
        Create a session-related error response.

        Args:
            conversation_id: Conversation identifier
            error_context: Context of the session error

        Returns:
            Session error response dictionary
        """
        error_messages = {
            ErrorContext.SESSION_NO_SESSION: "No active conversation found. Please start a new conversation.",
            ErrorContext.SESSION_EXPIRED: "Your conversation has expired. Please start a new conversation.",
            ErrorContext.SESSION_INVALID: "Invalid conversation state. Please start a new conversation.",
            ErrorContext.SESSION_MANAGEMENT: "I'm having trouble with our conversation. Please try starting over."
        }
        
        message = error_messages.get(error_context, error_messages[ErrorContext.SESSION_MANAGEMENT])
        
        return self.create_error_response(
            conversation_id=conversation_id,
            error_type="error",
            error_message=message,
            context=error_context
        )

    def create_audio_error_response(self, conversation_id: str, error_context: ErrorContext = ErrorContext.AUDIO_PROCESSING) -> Dict[str, Any]:
        """
        Create an audio-related error response.

        Args:
            conversation_id: Conversation identifier
            error_context: Context of the audio error

        Returns:
            Audio error response dictionary
        """
        error_messages = {
            ErrorContext.AUDIO_CONVERSION: "I'm having trouble processing your audio. Please try again.",
            ErrorContext.AUDIO_BUFFER_OPERATION: "I'm having trouble with audio processing. Please try again.",
            ErrorContext.AUDIO_PROCESSING: "I'm having trouble with audio. Please try again."
        }
        
        message = error_messages.get(error_context, error_messages[ErrorContext.AUDIO_PROCESSING])
        
        return self.create_error_response(
            conversation_id=conversation_id,
            error_type="error",
            error_message=message,
            context=error_context
        )

    def create_lex_api_error_response(self, conversation_id: str, error_code: str, error_message: str) -> Dict[str, Any]:
        """
        Create a Lex API error response.

        Args:
            conversation_id: Conversation identifier
            error_code: AWS error code
            error_message: AWS error message

        Returns:
            Lex API error response dictionary
        """
        user_friendly_message = self._get_user_friendly_lex_error_message(error_code)
        
        response = {
            "conversation_id": conversation_id,
            "message_type": "error",
            "text": user_friendly_message,
            "audio_content": b"",
            "barge_in_enabled": False,
            "response_type": "final",
            "error_context": ErrorContext.LEX_API_CALL.value,
            "aws_error_code": error_code,
            "aws_error_message": error_message,
            "input_mode": 3,  # INPUT_VOICE_DTMF = 3 (from protobuf)
            "input_handling_config": {
                "dtmf_config": {
                    "inter_digit_timeout_msec": 5000,  # 5 second timeout between digits
                    "dtmf_input_length": 10  # Allow up to 10 digits
                }
            }
        }
        
        return response

    def _get_user_friendly_lex_error_message(self, error_code: str) -> str:
        """
        Convert AWS error codes to user-friendly messages.

        Args:
            error_code: AWS error code

        Returns:
            User-friendly error message
        """
        error_messages = {
            "AccessDenied": "I don't have permission to access that service. Please contact support.",
            "InvalidParameterValue": "I received invalid information. Please try again.",
            "ResourceNotFoundException": "The requested service is not available. Please try again later.",
            "ThrottlingException": "I'm receiving too many requests. Please wait a moment and try again.",
            "InternalFailure": "I'm experiencing technical difficulties. Please try again later.",
            "ServiceUnavailable": "The service is temporarily unavailable. Please try again later."
        }
        
        return error_messages.get(error_code, "I'm experiencing technical difficulties. Please try again.")

    def log_error_summary(self, conversation_id: str, error_count: int, error_types: list) -> None:
        """
        Log a summary of errors for a conversation.

        Args:
            conversation_id: Conversation identifier
            error_count: Total number of errors
            error_types: List of error types encountered
        """
        if error_count > 0:
            self.logger.warning(f"Conversation {conversation_id} encountered {error_count} errors: {', '.join(error_types)}")
        else:
            self.logger.debug(f"Conversation {conversation_id} completed without errors")

    def should_retry_operation(self, error: Exception, retry_count: int, max_retries: int = 3) -> bool:
        """
        Determine if an operation should be retried.

        Args:
            error: The exception that occurred
            retry_count: Current retry attempt
            max_retries: Maximum number of retry attempts

        Returns:
            True if operation should be retried, False otherwise
        """
        if retry_count >= max_retries:
            return False
            
        # Retry on transient errors
        retryable_errors = [
            "ThrottlingException",
            "ServiceUnavailable",
            "InternalFailure"
        ]
        
        if isinstance(error, ClientError):
            error_code = error.response['Error']['Code']
            return error_code in retryable_errors
            
        # Retry on network-related exceptions
        network_errors = [
            "ConnectionError",
            "TimeoutError",
            "socket.timeout"
        ]
        
        error_type = type(error).__name__
        return error_type in network_errors

    def get_error_recovery_suggestion(self, error: Exception, context: ErrorContext) -> str:
        """
        Get a suggestion for error recovery.

        Args:
            error: The exception that occurred
            context: Context where the error occurred

        Returns:
            Recovery suggestion string
        """
        if isinstance(error, ClientError):
            error_code = error.response['Error']['Code']
            if error_code == "ThrottlingException":
                return "Wait a few seconds and try again"
            elif error_code == "AccessDenied":
                return "Check your AWS credentials and permissions"
            elif error_code == "ResourceNotFoundException":
                return "Verify the bot ID and alias are correct"
        
        if context == ErrorContext.AUDIO_PROCESSING:
            return "Try speaking more clearly or in a quieter environment"
        elif context in [ErrorContext.SESSION_MANAGEMENT, ErrorContext.SESSION_NO_SESSION, ErrorContext.SESSION_EXPIRED, ErrorContext.SESSION_INVALID]:
            return "Start a new conversation"
        elif context == ErrorContext.NETWORK:
            return "Check your internet connection and try again"
        
        return "Try again in a few moments"
