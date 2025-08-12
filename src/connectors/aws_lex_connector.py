"""
AWS Lex Connector implementation.

This connector integrates with Amazon Lex v2 to provide virtual agent capabilities.
It connects to existing AWS Lex instances and lists available bots as agents.
"""

import logging
from typing import Any, Dict, List

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from .i_vendor_connector import IVendorConnector


class AWSLexConnector(IVendorConnector):
    """
    AWS Lex connector for virtual agent integration.

    This connector connects to Amazon Lex v2 instances and provides
    access to Lex bots as virtual agents. It requires AWS credentials
    and region configuration.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialize the AWS Lex connector.

        Args:
            config: Configuration dictionary containing:
                   - 'region_name': AWS region (e.g., 'us-east-1')
                   - 'aws_access_key_id': AWS access key (optional, uses default credentials if not provided)
                   - 'aws_secret_access_key': AWS secret key (optional, uses default credentials if not provided)
                   - 'session_token': AWS session token (optional, for temporary credentials)
        """
        self.logger = logging.getLogger(__name__)

        # Extract configuration
        self.region_name = config.get("region_name")
        if not self.region_name:
            raise ValueError("AWS region_name is required in configuration")

        # AWS credentials (optional - will use default credentials if not provided)
        self.aws_access_key_id = config.get("aws_access_key_id")
        self.aws_secret_access_key = config.get("aws_secret_access_key")
        self.session_token = config.get("session_token")

        # Initialize AWS clients
        self._init_aws_clients()

        # Cache for available bots
        self._available_bots = None

        self.logger.info(f"AWSLexConnector initialized for region: {self.region_name}")

    def _init_aws_clients(self) -> None:
        """Initialize AWS clients for Lex operations."""
        try:
            # Create session with credentials if provided
            if self.aws_access_key_id and self.aws_secret_access_key:
                session = boto3.Session(
                    aws_access_key_id=self.aws_access_key_id,
                    aws_secret_access_key=self.aws_secret_access_key,
                    aws_session_token=self.session_token,
                    region_name=self.region_name
                )
            else:
                # Use default credentials
                session = boto3.Session(region_name=self.region_name)

            # Initialize Lex v2 client
            self.lex_client = session.client('lexv2-models')

            # Also initialize Lex runtime client for future conversation handling
            self.lex_runtime = session.client('lexv2-runtime')

            self.logger.info("AWS clients initialized successfully")

        except NoCredentialsError:
            self.logger.error("AWS credentials not found. Please configure AWS credentials.")
            raise
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

                # Extract bot IDs and names, format as "AWS: Bot Name"
                bot_identifiers = []
                for bot in bots:
                    bot_id = bot['botId']
                    bot_name = bot.get('botName', bot_id)  # Use bot name if available, fallback to ID
                    formatted_name = f"AWS: {bot_name}"
                    bot_identifiers.append(formatted_name)

                self._available_bots = bot_identifiers
                self.logger.info(f"Found {len(bot_identifiers)} available Lex bots: {bot_identifiers}")

            except ClientError as e:
                error_code = e.response['Error']['Code']
                error_message = e.response['Error']['Message']
                self.logger.error(f"AWS Lex API error ({error_code}): {error_message}")
                self._available_bots = []
            except Exception as e:
                self.logger.error(f"Unexpected error fetching Lex bots: {e}")
                self._available_bots = []

        return self._available_bots

    def start_conversation(
        self, conversation_id: str, request_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Start a virtual agent conversation with AWS Lex.

        Args:
            conversation_id: Unique identifier for the conversation
            request_data: Initial request data including agent ID

        Returns:
            Dictionary containing conversation initialization response
        """
        # For now, return a basic response indicating conversation started
        # This will be expanded in future iterations
        return {
            "text": "AWS Lex conversation started",
            "conversation_id": conversation_id,
            "agent_id": request_data.get("virtual_agent_id", "unknown"),
            "message_type": "conversation_start",
            "barge_in_enabled": True
        }

    def send_message(
        self, conversation_id: str, message_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send a message to the AWS Lex virtual agent.

        Args:
            conversation_id: Unique identifier for the conversation
            message_data: Message data including audio, text, or events

        Returns:
            Dictionary containing the virtual agent's response
        """
        # For now, return a basic response
        # This will be expanded in future iterations to actually call Lex
        return {
            "text": "AWS Lex message processing not yet implemented",
            "conversation_id": conversation_id,
            "message_type": "response",
            "barge_in_enabled": True
        }

    def end_conversation(self, conversation_id: str, message_data: Dict[str, Any] = None) -> None:
        """
        End a virtual agent conversation.

        Args:
            conversation_id: Unique identifier for the conversation to end
            message_data: Optional message data for the conversation end
        """
        self.logger.info(f"Ending AWS Lex conversation: {conversation_id}")
        # Cleanup logic will be implemented in future iterations

    def convert_wxcc_to_vendor(self, grpc_data: Any) -> Any:
        """
        Convert data from WxCC gRPC format to AWS Lex format.

        Args:
            grpc_data: Data in WxCC gRPC format (e.g., VoiceVARequest)

        Returns:
            Data converted to AWS Lex format
        """
        # This will be implemented in future iterations
        return grpc_data

    def convert_vendor_to_wxcc(self, vendor_data: Any) -> Any:
        """
        Convert data from AWS Lex format to WxCC gRPC format.

        Args:
            vendor_data: Data in AWS Lex format

        Returns:
            Data converted to WxCC gRPC format (e.g., VoiceVAResponse)
        """
        # This will be implemented in future iterations
        return vendor_data

    def _refresh_bot_cache(self) -> None:
        """Refresh the cached list of available bots."""
        self._available_bots = None
        self.get_available_agents()
