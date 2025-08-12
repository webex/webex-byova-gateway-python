"""
AWS Lex Connector for Webex Contact Center BYOVA Gateway.

This connector integrates with AWS Lex v2 to provide virtual agent capabilities.
It handles voice and text interactions with Lex bots using the standard TSTALIASID.
"""

import logging
from typing import Dict, Any, List
from botocore.exceptions import ClientError
import boto3

from .i_vendor_connector import IVendorConnector


class AWSLexConnector(IVendorConnector):
    """
    AWS Lex v2 connector for virtual agent integration.
    
    This connector provides a simple interface to AWS Lex bots using the
    standard TSTALIASID alias that most Lex bots have by default.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the AWS Lex connector.
        
        Args:
            config: Configuration dictionary containing:
                - region_name: AWS region (required)
                - aws_access_key_id: AWS access key (optional, uses default chain)
                - aws_secret_access_key: AWS secret key (optional, uses default chain)
        """
        # Extract configuration
        self.region_name = config.get('region_name')
        if not self.region_name:
            raise ValueError("region_name is required in AWS Lex connector configuration")
            
        # Optional explicit AWS credentials
        self.aws_access_key_id = config.get('aws_access_key_id')
        self.aws_secret_access_key = config.get('aws_secret_access_key')
        
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
        
        self.logger.info(f"AWSLexConnector initialized for region: {self.region_name}")

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
            self.lex_client = session.client('lexv2-models')  # For bot management
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
            Response data for the new conversation
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

            return {
                "text": f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                "conversation_id": conversation_id,
                "message_type": "welcome",
                "barge_in_enabled": True
            }

        except Exception as e:
            self.logger.error(f"Error starting Lex conversation: {e}")
            return {
                "text": "I'm having trouble starting our conversation. Please try again.",
                "conversation_id": conversation_id,
                "message_type": "error",
                "barge_in_enabled": False
            }

    def send_message(self, conversation_id: str, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a message to the Lex bot in an active conversation.
        
        Args:
            conversation_id: Active conversation identifier
            message_data: Message data containing input (audio or text)
            
        Returns:
            Response from the Lex bot
        """
        if conversation_id not in self._sessions:
            return {
                "text": "No active conversation session. Please start a new conversation.",
                "conversation_id": conversation_id,
                "message_type": "error",
                "barge_in_enabled": False
            }

        session_info = self._sessions[conversation_id]
        input_type = message_data.get("input_type", "text")

        if input_type == "audio":
            return self._send_audio_to_lex(message_data, conversation_id)
        else:
            return self._send_text_to_lex(message_data, conversation_id)

    def _send_audio_to_lex(self, message_data: Dict[str, Any], conversation_id: str) -> Dict[str, Any]:
        """
        Send audio input to Lex bot.
        
        Args:
            message_data: Message data containing audio
            conversation_id: Active conversation identifier
            
        Returns:
            Response from Lex bot
        """
        if conversation_id not in self._sessions:
            return {
                "text": "No active conversation session. Please start a new conversation.",
                "conversation_id": conversation_id,
                "message_type": "error",
                "barge_in_enabled": False
            }

        session_info = self._sessions[conversation_id]
        audio_data = message_data.get("audio_data", {})
        audio_bytes = audio_data.get("audio_bytes", b"")

        if not audio_bytes:
            return {
                "text": "I didn't receive any audio. Please try again.",
                "conversation_id": conversation_id,
                "message_type": "error",
                "barge_in_enabled": True
            }

        try:
            self.logger.info(f"Sending audio to Lex (size: {len(audio_bytes)} bytes)")

            # For minimal implementation, we'll use RecognizeUtterance
            # Note: This requires the bot to have an alias configured
            try:
                response = self.lex_runtime.recognize_utterance(
                    botId=session_info["actual_bot_id"],  # Use actual bot ID from mapping
                    botAliasId='TSTALIASID',  # Use standard test alias
                    localeId='en_US',
                    sessionId=session_info["session_id"],
                    requestContentType='audio/ogg; charset=utf-8',
                    responseContentType='text/plain; charset=utf-8',
                    inputStream=audio_bytes
                )

                # Extract response from Lex
                response_content = response.get('responseContent', '')
                if response_content:
                    response_text = response_content
                else:
                    response_text = 'I heard you, but I need more context.'

                self.logger.info(f"Lex audio response: {response_text}")

                return {
                    "text": response_text,
                    "conversation_id": conversation_id,
                    "message_type": "response",
                    "barge_in_enabled": True
                }

            except ClientError as e:
                error_code = e.response['Error']['Code']
                if error_code == 'NotFoundException':
                    error_message = "Bot not found. Please check your bot configuration."
                elif error_code == 'UnsupportedMediaTypeException':
                    error_message = "Audio format not supported. Please try a different format."
                else:
                    error_message = f"AWS Lex error: {error_code}"
                
                self.logger.error(f"Lex API error: {e}")
                return {
                    "text": error_message,
                    "conversation_id": conversation_id,
                    "message_type": "error",
                    "barge_in_enabled": True
                }

        except Exception as e:
            self.logger.error(f"Error sending audio to Lex: {e}")
            return {
                "text": "I'm having trouble processing your audio. Please try again.",
                "conversation_id": conversation_id,
                "message_type": "error",
                "barge_in_enabled": True
            }

    def _send_text_to_lex(self, message_data: Dict[str, Any], conversation_id: str) -> Dict[str, Any]:
        """
        Send text input to Lex bot.
        
        Args:
            message_data: Message data containing text
            conversation_id: Active conversation identifier
            
        Returns:
            Response from Lex bot
        """
        if conversation_id not in self._sessions:
            return {
                "text": "No active conversation session. Please start a new conversation.",
                "conversation_id": conversation_id,
                "message_type": "error",
                "barge_in_enabled": False
            }

        session_info = self._sessions[conversation_id]
        text_data = message_data.get("text_data", {})
        text_input = text_data.get("text", "")

        if not text_input:
            return {
                "text": "I didn't receive any text. Please try again.",
                "conversation_id": conversation_id,
                "message_type": "error",
                "barge_in_enabled": True
            }

        try:
            self.logger.info(f"Sending text to Lex: '{text_input}'")

            response = self.lex_runtime.recognize_text(
                botId=session_info["actual_bot_id"],  # Use actual bot ID from mapping
                botAliasId='TSTALIASID',  # Use standard test alias
                localeId='en_US',
                sessionId=session_info["session_id"],
                text=text_input
            )

            # Extract response from Lex
            messages = response.get('messages', [])
            if messages:
                response_text = messages[0].get('content', 'I heard you, but I need more context.')
            else:
                response_text = 'I heard you, but I need more context.'

            self.logger.info(f"Lex text response: {response_text}")

            return {
                "text": response_text,
                "conversation_id": conversation_id,
                "message_type": "response",
                "barge_in_enabled": True
            }

        except Exception as e:
            self.logger.error(f"Error sending text to Lex: {e}")
            return {
                "text": "I'm having trouble processing your text. Please try again.",
                "conversation_id": conversation_id,
                "message_type": "error",
                "barge_in_enabled": True
            }

    def end_conversation(self, conversation_id: str, message_data: Dict[str, Any] = None) -> None:
        """
        End an active conversation and clean up resources.
        
        Args:
            conversation_id: Active conversation identifier
            message_data: Optional final message data
        """
        if conversation_id in self._sessions:
            bot_name = self._sessions[conversation_id].get("bot_name", "unknown")
            del self._sessions[conversation_id]
            self.logger.info(f"Ended Lex conversation: {conversation_id} with bot: {bot_name}")

    def convert_wxcc_to_vendor(self, wxcc_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert Webex Contact Center data format to vendor format.
        
        Args:
            wxcc_data: Data in WxCC format
            
        Returns:
            Data converted to vendor format
        """
        # For now, just return the data as-is
        # This can be enhanced later for specific format conversions
        return wxcc_data

    def convert_vendor_to_wxcc(self, vendor_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert vendor data format to Webex Contact Center format.
        
        Args:
            vendor_data: Data in vendor format
            
        Returns:
            Data converted to WxCC format
        """
        # For now, just return the data as-is
        # This can be enhanced later for specific format conversions
        return vendor_data

    def _refresh_bot_cache(self) -> None:
        """Refresh the cached list of available bots."""
        self._available_bots = None
        self._bot_name_to_id_map = {}  # Clear the mapping cache too
        self.get_available_agents()
