"""
AWS Lex Connector for Webex Contact Center BYOVA Gateway.

This connector integrates with AWS Lex v2 to provide virtual agent capabilities.
It handles basic agent discovery and conversation initialization.
"""

import logging
from typing import Dict, Any, List
from botocore.exceptions import ClientError
import boto3

from .i_vendor_connector import IVendorConnector
from ..utils.audio_utils import convert_aws_lex_audio_to_wxcc


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
                # Convert text to bytes for the request
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
                        self.logger.info(f"Audio content is valid, returning response with audio")
                        
                        # Use the audio utility to convert AWS Lex audio to WxCC-compatible format
                        # AWS Lex returns 16kHz, 16-bit PCM, but WxCC expects 8kHz, 8-bit u-law
                        wav_audio, content_type = convert_aws_lex_audio_to_wxcc(
                            audio_response, 
                            bit_depth=16       # Lex returns 16-bit PCM
                        )
                        
                        return {
                            "text": f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                            "audio_content": wav_audio,
                            "conversation_id": conversation_id,
                            "message_type": "welcome",
                            "barge_in_enabled": True,
                            "content_type": content_type
                        }
                    else:
                        self.logger.warning("Audio stream was empty, falling back to text-only response")
                        return {
                            "text": f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                            "audio_content": b"",
                            "conversation_id": conversation_id,
                            "message_type": "welcome",
                            "barge_in_enabled": False
                        }
                else:
                    self.logger.error("No audio stream in Lex response")
                    # Check if there are other fields in the response
                    if hasattr(response, 'messages'):
                        self.logger.info(f"Lex messages: {response.messages}")
                    if hasattr(response, 'intentName'):
                        self.logger.info(f"Lex intent: {response.intentName}")
                    
                    return {
                        "text": f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                        "audio_content": b"",
                        "conversation_id": conversation_id,
                        "message_type": "welcome",
                        "barge_in_enabled": False
                    }
                    
            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_message = e.response['Error']['Message']
                self.logger.error(f"Lex API error during conversation start: {error_code} - {error_message}")
                
                # Fallback to text response
                return {
                    "text": f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                    "audio_content": b"",
                    "conversation_id": conversation_id,
                    "message_type": "welcome",
                    "barge_in_enabled": True
                }
                
            except Exception as e:
                self.logger.error(f"Error getting audio response from Lex: {e}")
                self.logger.error(f"Exception type: {type(e)}")
                import traceback
                self.logger.error(f"Traceback: {traceback.format_exc()}")
                
                # Fallback to text response
                return {
                    "text": f"Hello! I'm your {bot_name} assistant. How can I help you today?",
                    "audio_content": b"",
                    "conversation_id": conversation_id,
                    "message_type": "welcome",
                    "barge_in_enabled": True
                }

        except Exception as e:
            self.logger.error(f"Error starting Lex conversation: {e}")
            self.logger.error(f"Exception type: {type(e)}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                "text": "I'm having trouble starting our conversation. Please try again.",
                "audio_content": b"",
                "conversation_id": conversation_id,
                "message_type": "error",
                "barge_in_enabled": False
            }

    def send_message(self, conversation_id: str, message_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Placeholder method for sending messages - functionality removed for debugging.
        
        Args:
            conversation_id: Active conversation identifier
            message_data: Message data containing input (audio or text)
            
        Returns:
            Placeholder response indicating functionality is disabled
        """
        return {
            "text": "Message handling functionality has been temporarily disabled for debugging.",
            "conversation_id": conversation_id,
            "message_type": "silence",
            "barge_in_enabled": False
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
