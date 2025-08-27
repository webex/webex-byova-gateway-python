"""
AWS Lex Session Manager for Webex Contact Center BYOVA Gateway.

This module handles all session-related operations for the AWS Lex connector,
including session lifecycle, bot management, and conversation state tracking.
"""

import logging
from typing import Any, Dict, List, Optional, Set

from botocore.exceptions import ClientError


class AWSLexSessionManager:
    """
    Manages all session-related operations for AWS Lex connector.
    
    This class encapsulates session lifecycle, bot discovery, and conversation
    state tracking to keep the main connector focused on business logic.
    """

    def __init__(self, logger: logging.Logger):
        """
        Initialize the session manager.

        Args:
            logger: Logger instance for the connector
        """
        self.logger = logger
        
        # Cache for available bots
        self._available_bots = None
        
        # Mapping from display names to actual bot IDs
        self._bot_name_to_id_map = {}
        
        # Simple session storage for conversations
        self._sessions = {}
        
        # Track which conversations have already sent START_OF_INPUT event
        self.conversations_with_start_of_input: Set[str] = set()

    def get_available_agents(self, lex_client) -> List[str]:
        """
        Get available virtual agent IDs from AWS Lex.

        Args:
            lex_client: AWS Lex client for bot discovery

        Returns:
            List of Lex bot IDs that can be used as virtual agents
        """
        if self._available_bots is None:
            try:
                self.logger.debug("Fetching available Lex bots...")

                # List all bots in the region
                response = lex_client.list_bots()
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
                self.logger.debug(f"Bot mappings: {self._bot_name_to_id_map}")

            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_message = e.response['Error']['Message']
                self.logger.error(f"AWS Lex API error ({error_code}): {error_message}")
                self._available_bots = []
            except Exception as e:
                self.logger.error(f"Unexpected error fetching Lex bots: {e}")
                self._available_bots = []

        return self._available_bots

    def create_session(self, conversation_id: str, display_name: str) -> Dict[str, Any]:
        """
        Create a new session for a conversation.

        Args:
            conversation_id: Unique conversation identifier
            display_name: Display name from WxCC (e.g., "aws_lex_connector: Booking")

        Returns:
            Session information dictionary

        Raises:
            ValueError: If bot is not found in mapping
        """
        # Look up the actual bot ID from our mapping
        actual_bot_id = self._bot_name_to_id_map.get(display_name)
        if not actual_bot_id:
            raise ValueError(f"Bot not found in mapping: {display_name}. Available bots: {list(self._bot_name_to_id_map.keys())}")

        # Extract the friendly bot name for display
        bot_name = display_name.split(": ", 1)[1] if ": " in display_name else display_name

        # Create a simple session ID for Lex
        session_id = f"session_{conversation_id}"

        # Store session info with both names
        session_info = {
            "session_id": session_id,
            "display_name": display_name,      # "aws_lex_connector: Booking"
            "actual_bot_id": actual_bot_id,    # "E7LNGX7D2J"
            "bot_name": bot_name               # "Booking"
        }
        
        self._sessions[conversation_id] = session_info

        self.logger.info(f"Started Lex conversation: {conversation_id} with bot: {bot_name} (ID: {actual_bot_id})")
        self.logger.debug(f"Session created: {session_info}")
        
        return session_info

    def get_session(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get session information for a conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            Session information dictionary or None if not found
        """
        return self._sessions.get(conversation_id)

    def has_session(self, conversation_id: str) -> bool:
        """
        Check if a session exists for a conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            True if session exists, False otherwise
        """
        return conversation_id in self._sessions

    def get_bot_id(self, conversation_id: str) -> Optional[str]:
        """
        Get the bot ID for a conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            Bot ID or None if session not found
        """
        session_info = self._sessions.get(conversation_id)
        return session_info.get("actual_bot_id") if session_info else None

    def get_session_id(self, conversation_id: str) -> Optional[str]:
        """
        Get the session ID for a conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            Session ID or None if session not found
        """
        session_info = self._sessions.get(conversation_id)
        return session_info.get("session_id") if session_info else None

    def get_bot_name(self, conversation_id: str) -> Optional[str]:
        """
        Get the bot name for a conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            Bot name or None if session not found
        """
        session_info = self._sessions.get(conversation_id)
        return session_info.get("bot_name") if session_info else None

    def end_session(self, conversation_id: str, message_data: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        End a session and clean up resources.

        Args:
            conversation_id: Conversation identifier
            message_data: Optional final message data

        Returns:
            Session info that was cleaned up, or None if no session existed
        """
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
                return session_info
            
            return session_info
        else:
            self.logger.warning(f"Attempted to end non-existent conversation: {conversation_id}")
            return None

    def add_start_of_input_tracking(self, conversation_id: str) -> None:
        """
        Add a conversation to START_OF_INPUT tracking.

        Args:
            conversation_id: Conversation identifier
        """
        self.conversations_with_start_of_input.add(conversation_id)
        self.logger.debug(f"Added conversation {conversation_id} to START_OF_INPUT tracking")

    def remove_start_of_input_tracking(self, conversation_id: str) -> None:
        """
        Remove a conversation from START_OF_INPUT tracking.

        Args:
            conversation_id: Conversation identifier
        """
        if conversation_id in self.conversations_with_start_of_input:
            self.conversations_with_start_of_input.remove(conversation_id)
            self.logger.debug(f"Removed conversation {conversation_id} from START_OF_INPUT tracking")
        else:
            self.logger.debug(f"Conversation {conversation_id} was not in START_OF_INPUT tracking")

    def has_start_of_input_tracking(self, conversation_id: str) -> bool:
        """
        Check if a conversation has START_OF_INPUT tracking.

        Args:
            conversation_id: Conversation identifier

        Returns:
            True if conversation has START_OF_INPUT tracking, False otherwise
        """
        return conversation_id in self.conversations_with_start_of_input

    def reset_conversation_for_next_input(self, conversation_id: str) -> None:
        """
        Reset the conversation state to prepare for the next audio input cycle.
        
        This method should be called after successfully sending a final response to WxCC
        to prepare the conversation for handling the next round of audio input.
        
        Args:
            conversation_id: Conversation identifier to reset
        """
        try:
            # Remove from START_OF_INPUT tracking to allow new audio input cycle
            self.remove_start_of_input_tracking(conversation_id)
            
            # Log the successful reset
            self.logger.debug(f"Conversation {conversation_id} reset for next audio input cycle")
            
        except Exception as e:
            self.logger.error(f"Error resetting conversation {conversation_id} for next input: {e}")
            # Don't raise the exception, continue with conversation

    def refresh_bot_cache(self) -> None:
        """Refresh the cached list of available bots."""
        self._available_bots = None
        self._bot_name_to_id_map = {}  # Clear the mapping cache too
        self.logger.debug("Bot cache cleared, will refresh on next get_available_agents call")

    def get_bot_mapping(self, display_name: str) -> Optional[str]:
        """
        Get the actual bot ID for a display name.

        Args:
            display_name: Display name (e.g., "aws_lex_connector: Booking")

        Returns:
            Actual bot ID or None if not found
        """
        return self._bot_name_to_id_map.get(display_name)

    def get_all_bot_mappings(self) -> Dict[str, str]:
        """
        Get all bot name to ID mappings.

        Returns:
            Dictionary of display_name -> actual_bot_id mappings
        """
        return self._bot_name_to_id_map.copy()

    def get_session_count(self) -> int:
        """
        Get the current number of active sessions.

        Returns:
            Number of active sessions
        """
        return len(self._sessions)

    def get_start_of_input_count(self) -> int:
        """
        Get the current number of conversations with START_OF_INPUT tracking.

        Returns:
            Number of conversations with START_OF_INPUT tracking
        """
        return len(self.conversations_with_start_of_input)

    def get_session_info(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get comprehensive session information for a conversation.

        Args:
            conversation_id: Conversation identifier

        Returns:
            Dictionary with session details or None if not found
        """
        if conversation_id not in self._sessions:
            return None
            
        session_info = self._sessions[conversation_id]
        return {
            'conversation_id': conversation_id,
            'session_id': session_info.get('session_id'),
            'bot_id': session_info.get('actual_bot_id'),
            'bot_name': session_info.get('bot_name'),
            'display_name': session_info.get('display_name'),
            'has_start_of_input_tracking': conversation_id in self.conversations_with_start_of_input
        }

    def cleanup_all_sessions(self) -> None:
        """
        Clean up all sessions and tracking.
        
        This is useful for shutdown or testing purposes.
        """
        session_count = len(self._sessions)
        tracking_count = len(self.conversations_with_start_of_input)
        
        self._sessions.clear()
        self.conversations_with_start_of_input.clear()
        
        self.logger.info(f"Cleaned up {session_count} sessions and {tracking_count} tracking entries")
