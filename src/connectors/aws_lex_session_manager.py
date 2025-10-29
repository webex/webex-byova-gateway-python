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
        
        # Mapping from bot IDs to their most recent alias IDs
        self._bot_alias_map = {}
        
        # Simple session storage for conversations
        self._sessions = {}
        
        # Track which conversations have already sent START_OF_INPUT event
        self.conversations_with_start_of_input: Set[str] = set()
        
        # Track which conversations are currently in DTMF input mode
        self.conversations_in_dtmf_mode: Set[str] = set()

    def get_available_agents(self, lex_client) -> List[str]:
        """
        Get available virtual agent IDs from AWS Lex.
        
        This method discovers bots and their most recent aliases automatically.

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
                    
                    # Discover the most recent alias for this bot
                    alias_id = self._discover_most_recent_alias(lex_client, bot_id, bot_name)
                    
                    # Only include bots that have at least one alias
                    if alias_id:
                        display_name = f"aws_lex_connector: {bot_name}"
                        
                        # Store the mappings
                        self._bot_name_to_id_map[display_name] = bot_id
                        self._bot_alias_map[bot_id] = alias_id
                        
                        bot_identifiers.append(display_name)
                        self.logger.debug(f"Bot '{bot_name}' (ID: {bot_id}) will use alias: {alias_id}")
                    else:
                        self.logger.warning(f"Skipping bot '{bot_name}' (ID: {bot_id}) - no aliases found")

                self._available_bots = bot_identifiers
                self.logger.info(f"Found {len(bot_identifiers)} available Lex bots with aliases: {bot_identifiers}")
                self.logger.debug(f"Bot mappings: {self._bot_name_to_id_map}")
                self.logger.debug(f"Bot alias mappings: {self._bot_alias_map}")

            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_message = e.response['Error']['Message']
                self.logger.error(f"AWS Lex API error ({error_code}): {error_message}")
                self._available_bots = []
            except Exception as e:
                self.logger.error(f"Unexpected error fetching Lex bots: {e}")
                self._available_bots = []

        return self._available_bots
    
    def _discover_most_recent_alias(self, lex_client, bot_id: str, bot_name: str) -> Optional[str]:
        """
        Discover the most recent alias for a bot.
        
        Args:
            lex_client: AWS Lex client
            bot_id: The bot ID to get aliases for
            bot_name: The bot name (for logging)
            
        Returns:
            The most recent alias ID, or None if no aliases exist
        """
        try:
            self.logger.debug(f"Fetching aliases for bot '{bot_name}' (ID: {bot_id})")
            
            # List all aliases for this bot
            response = lex_client.list_bot_aliases(botId=bot_id)
            aliases = response.get('botAliasSummaries', [])
            
            if not aliases:
                self.logger.warning(f"No aliases found for bot '{bot_name}' (ID: {bot_id})")
                return None
            
            # Sort aliases by lastUpdatedDateTime (most recent first)
            # If lastUpdatedDateTime is not available, fall back to createdDateTime
            sorted_aliases = sorted(
                aliases,
                key=lambda a: a.get('lastUpdatedDateTime', a.get('createdDateTime')),
                reverse=True
            )
            
            # Get the most recent alias
            most_recent = sorted_aliases[0]
            alias_id = most_recent.get('botAliasId')
            alias_name = most_recent.get('botAliasName', alias_id)
            
            self.logger.info(f"Selected most recent alias '{alias_name}' (ID: {alias_id}) for bot '{bot_name}'")
            return alias_id
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            error_message = e.response['Error']['Message']
            self.logger.error(f"AWS Lex API error fetching aliases for bot '{bot_name}' ({error_code}): {error_message}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error fetching aliases for bot '{bot_name}': {e}")
            return None

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

        # Get the bot alias ID for this bot
        bot_alias_id = self._bot_alias_map.get(actual_bot_id)
        if not bot_alias_id:
            raise ValueError(f"No alias found for bot ID: {actual_bot_id}")

        # Extract the friendly bot name for display
        bot_name = display_name.split(": ", 1)[1] if ": " in display_name else display_name

        # Create a simple session ID for Lex
        session_id = f"session_{conversation_id}"

        # Store session info with both names and alias
        session_info = {
            "session_id": session_id,
            "display_name": display_name,      # "aws_lex_connector: Booking"
            "actual_bot_id": actual_bot_id,    # "E7LNGX7D2J"
            "bot_name": bot_name,              # "Booking"
            "bot_alias_id": bot_alias_id       # "TSTALIASID" or other discovered alias
        }
        
        self._sessions[conversation_id] = session_info

        self.logger.info(f"Started Lex conversation: {conversation_id} with bot: {bot_name} (ID: {actual_bot_id}, Alias: {bot_alias_id})")
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
    
    def get_bot_alias_id(self, bot_id: str) -> Optional[str]:
        """
        Get the bot alias ID for a specific bot.

        Args:
            bot_id: Bot identifier

        Returns:
            Bot alias ID or None if not found
        """
        return self._bot_alias_map.get(bot_id)
    
    def get_bot_alias_id_for_session(self, conversation_id: str) -> Optional[str]:
        """
        Get the bot alias ID for a conversation's session.

        Args:
            conversation_id: Conversation identifier

        Returns:
            Bot alias ID or None if session not found
        """
        session_info = self._sessions.get(conversation_id)
        return session_info.get("bot_alias_id") if session_info else None

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
            self.logger.debug(f"No session found for conversation: {conversation_id} (this may be normal for early termination)")
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

    def add_dtmf_mode_tracking(self, conversation_id: str) -> None:
        """
        Add a conversation to DTMF mode tracking.

        Args:
            conversation_id: Conversation identifier
        """
        self.conversations_in_dtmf_mode.add(conversation_id)
        self.logger.debug(f"Added conversation {conversation_id} to DTMF mode tracking")

    def remove_dtmf_mode_tracking(self, conversation_id: str) -> None:
        """
        Remove a conversation from DTMF mode tracking.

        Args:
            conversation_id: Conversation identifier
        """
        if conversation_id in self.conversations_in_dtmf_mode:
            self.conversations_in_dtmf_mode.remove(conversation_id)
            self.logger.debug(f"Removed conversation {conversation_id} from DTMF mode tracking")
        else:
            self.logger.debug(f"Conversation {conversation_id} was not in DTMF mode tracking")

    def has_dtmf_mode_tracking(self, conversation_id: str) -> bool:
        """
        Check if a conversation is in DTMF mode.

        Args:
            conversation_id: Conversation identifier

        Returns:
            True if conversation is in DTMF mode, False otherwise
        """
        return conversation_id in self.conversations_in_dtmf_mode



    def reset_conversation_for_next_input(self, conversation_id: str) -> None:
        """
        Reset the conversation state to prepare for the next audio input cycle.
        
        This method should be called after successfully sending a final response to WxCC
        to prepare the conversation for handling the next round of audio input.
        
        This method removes START_OF_INPUT tracking and DTMF mode tracking so that each audio segment
        can follow the same independent flow: speech detection -> START_OF_INPUT -> silence detection -> END_OF_INPUT.
        
        Args:
            conversation_id: Conversation identifier to reset
        """
        try:
            # Remove from START_OF_INPUT tracking to allow each segment to be independent
            self.remove_start_of_input_tracking(conversation_id)
            
            # Remove from DTMF mode tracking to allow speech detection to resume
            self.remove_dtmf_mode_tracking(conversation_id)
            
            # Log the successful reset
            self.logger.debug(f"Conversation {conversation_id} reset for next audio input cycle (START_OF_INPUT and DTMF mode tracking reset for independent segment flow)")
            
        except Exception as e:
            self.logger.error(f"Error resetting conversation {conversation_id} for next input: {e}")
            # Don't raise the exception, continue with conversation

    def refresh_bot_cache(self) -> None:
        """Refresh the cached list of available bots and their aliases."""
        self._available_bots = None
        self._bot_name_to_id_map = {}  # Clear the mapping cache too
        self._bot_alias_map = {}  # Clear the alias mapping cache too
        self.logger.debug("Bot cache and alias mappings cleared, will refresh on next get_available_agents call")

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

    def get_dtmf_mode_count(self) -> int:
        """
        Get the current number of conversations in DTMF mode.

        Returns:
            Number of conversations in DTMF mode
        """
        return len(self.conversations_in_dtmf_mode)



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
            'bot_alias_id': session_info.get('bot_alias_id'),
            'display_name': session_info.get('display_name'),
            'has_start_of_input_tracking': conversation_id in self.conversations_with_start_of_input,
            'has_dtmf_mode_tracking': conversation_id in self.conversations_in_dtmf_mode
        }

    def cleanup_all_sessions(self) -> None:
        """
        Clean up all sessions and tracking.
        
        This is useful for shutdown or testing purposes.
        """
        session_count = len(self._sessions)
        start_of_input_count = len(self.conversations_with_start_of_input)
        dtmf_mode_count = len(self.conversations_in_dtmf_mode)
        
        self._sessions.clear()
        self.conversations_with_start_of_input.clear()
        self.conversations_in_dtmf_mode.clear()
        
        self.logger.info(f"Cleaned up {session_count} sessions, {start_of_input_count} START_OF_INPUT tracking entries, and {dtmf_mode_count} DTMF mode tracking entries")
