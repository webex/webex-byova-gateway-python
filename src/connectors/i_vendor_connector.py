"""
Abstract base class for vendor connector implementations.

This module defines the interface that all vendor connectors must implement
to integrate with the Webex Contact Center BYOVA Gateway.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class IVendorConnector(ABC):
    """
    Abstract base class for vendor connector implementations.

    All vendor connectors must inherit from this class and implement
    the required abstract methods to provide a unified interface
    for virtual agent communication.
    """

    @abstractmethod
    def __init__(self, config: Dict[str, Any]) -> None:
        """
        Initialize the connector with configuration data.

        Args:
            config: Configuration dictionary containing vendor-specific settings
                   such as API endpoints, authentication credentials, etc.
        """
        pass

    @abstractmethod
    def start_conversation(
        self, conversation_id: str, request_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Start a virtual agent conversation.

        Args:
            conversation_id: Unique identifier for the conversation
            request_data: Initial request data including agent ID, user info, etc.

        Returns:
            Dictionary containing conversation initialization response from the vendor
        """
        pass

    @abstractmethod
    def send_message(
        self, conversation_id: str, message_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send a message or audio to the virtual agent.

        Args:
            conversation_id: Unique identifier for the conversation
            message_data: Message data including audio bytes, text, or events

        Returns:
            Dictionary containing the virtual agent's response
        """
        pass

    @abstractmethod
    def end_conversation(self, conversation_id: str, message_data: Dict[str, Any] = None) -> None:
        """
        End a virtual agent conversation.

        Args:
            conversation_id: Unique identifier for the conversation to end
            message_data: Optional message data for the conversation end (default: None)
        """
        pass

    @abstractmethod
    def get_available_agents(self) -> List[str]:
        """
        Get a list of available virtual agent IDs.

        Returns:
            List of virtual agent ID strings that this connector can provide
        """
        pass

    @abstractmethod
    def convert_wxcc_to_vendor(self, grpc_data: Any) -> Any:
        """
        Convert data from WxCC gRPC format to vendor's native format.

        Args:
            grpc_data: Data in WxCC gRPC format (e.g., VoiceVARequest)

        Returns:
            Data converted to vendor's native format
        """
        pass

    @abstractmethod
    def convert_vendor_to_wxcc(self, vendor_data: Any) -> Any:
        """
        Convert data from vendor's native format to WxCC gRPC format.

        Args:
            vendor_data: Data in vendor's native format

        Returns:
            Data converted to WxCC gRPC format (e.g., VoiceVAResponse)
        """
        pass
