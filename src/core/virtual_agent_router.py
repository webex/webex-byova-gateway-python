"""
Virtual Agent Router implementation.

This module provides routing functionality to manage multiple vendor connectors
and route requests to the appropriate connector based on agent ID.
"""

import importlib
import logging
from typing import Any, Dict, List

from src.connectors.i_vendor_connector import IVendorConnector


class VirtualAgentRouter:
    """
    Router for managing virtual agent connectors.
    
    This class handles loading and routing requests to appropriate
    vendor connector implementations based on agent ID.
    """
    
    def __init__(self) -> None:
        """
        Initialize the virtual agent router.
        
        Creates empty dictionaries to store connector instances and
        agent-to-connector mappings.
        """
        # Dictionary to store loaded connector instances
        # Key: connector identifier (e.g., "local_audio", "vendor_x")
        # Value: IVendorConnector instance
        self.loaded_connectors: Dict[str, IVendorConnector] = {}
        
        # Dictionary to map agent IDs to their connector instances
        # Key: agent ID (e.g., "Local Playback", "Vendor X Agent 1")
        # Value: IVendorConnector instance
        self.agent_to_connector_map: Dict[str, IVendorConnector] = {}
        
        # Set up logging
        self.logger = logging.getLogger(__name__)
        
        self.logger.info("VirtualAgentRouter initialized")
    
    def load_connectors(self, config: Dict[str, Any]) -> None:
        """
        Load connector instances from configuration.
        
        Args:
            config: Configuration dictionary containing connector definitions.
                   Expected format:
                   {
                       "connectors": {
                           "local_audio": {
                               "class": "LocalAudioConnector",
                               "module": "connectors.local_audio_connector",
                               "config": {
                                   "agent_id": "Local Playback",
                                   "audio_base_path": "audio"
                               }
                           },
                           "vendor_x": {
                               "class": "VendorXConnector", 
                               "module": "connectors.vendor_x_connector",
                               "config": {
                                   "api_key": "xxx",
                                   "endpoint": "https://api.vendorx.com"
                               }
                           }
                       }
                   }
        """
        self.logger.info("Loading connectors from configuration")
        
        connectors_config = config.get('connectors', {})
        
        for connector_id, connector_config in connectors_config.items():
            try:
                # Extract connector configuration
                class_name = connector_config.get('class')
                module_name = connector_config.get('module')
                connector_specific_config = connector_config.get('config', {})
                
                if not class_name or not module_name:
                    self.logger.error(f"Missing 'class' or 'module' for connector {connector_id}")
                    continue
                
                # Dynamically import the connector class
                try:
                    module = importlib.import_module(f"src.{module_name}")
                    connector_class = getattr(module, class_name)
                except (ImportError, AttributeError) as e:
                    self.logger.error(f"Failed to import {class_name} from {module_name}: {e}")
                    continue
                
                # Verify it's a valid connector
                if not issubclass(connector_class, IVendorConnector):
                    self.logger.error(f"{class_name} does not inherit from IVendorConnector")
                    continue
                
                # Instantiate the connector
                connector_instance = connector_class(connector_specific_config)
                
                # Get available agents from this connector
                available_agents = connector_instance.get_available_agents()
                
                # Map each agent to this connector
                for agent_id in available_agents:
                    self.agent_to_connector_map[agent_id] = connector_instance
                    self.logger.info(f"Mapped agent '{agent_id}' to connector '{connector_id}'")
                
                # Store the connector instance
                self.loaded_connectors[connector_id] = connector_instance
                
                self.logger.info(f"Successfully loaded connector '{connector_id}' ({class_name}) "
                               f"with {len(available_agents)} agents: {available_agents}")
                
            except Exception as e:
                self.logger.error(f"Failed to load connector {connector_id}: {e}")
                continue
        
        self.logger.info(f"Router loaded {len(self.loaded_connectors)} connectors "
                        f"with {len(self.agent_to_connector_map)} total agents")
    
    def get_all_available_agents(self) -> List[str]:
        """
        Get a list of all available virtual agent IDs.
        
        Returns:
            List of all unique virtual agent IDs registered in the router
        """
        return list(self.agent_to_connector_map.keys())
    
    def get_connector_for_agent(self, agent_id: str) -> IVendorConnector:
        """
        Get the connector instance for a specific agent ID.
        
        Args:
            agent_id: The virtual agent ID to look up
            
        Returns:
            The IVendorConnector instance for the specified agent
            
        Raises:
            ValueError: If the agent_id is not found
        """
        if agent_id not in self.agent_to_connector_map:
            available_agents = list(self.agent_to_connector_map.keys())
            raise ValueError(f"Agent '{agent_id}' not found. Available agents: {available_agents}")
        
        return self.agent_to_connector_map[agent_id]
    
    def route_request(self, agent_id: str, method: str, *args, **kwargs) -> Any:
        """
        Route a request to the appropriate connector.
        
        This is the primary entry point for the WxCC gRPC server to interact
        with connectors. It routes requests based on agent ID and method name.
        
        Args:
            agent_id: The virtual agent ID to route the request to
            method: The method to call on the connector (e.g., "start_session", "send_message")
            *args: Positional arguments to pass to the method
            **kwargs: Keyword arguments to pass to the method
            
        Returns:
            The result from the connector method call
            
        Raises:
            ValueError: If the agent_id is not found
            AttributeError: If the method doesn't exist on the connector
        """
        self.logger.debug(f"Routing request: agent_id={agent_id}, method={method}, args={args}, kwargs={kwargs}")
        
        # Get the appropriate connector
        connector = self.get_connector_for_agent(agent_id)
        
        # Verify the method exists
        if not hasattr(connector, method):
            available_methods = [attr for attr in dir(connector) if not attr.startswith('_')]
            raise AttributeError(f"Method '{method}' not found on connector. Available methods: {available_methods}")
        
        # Call the method on the connector
        method_func = getattr(connector, method)
        result = method_func(*args, **kwargs)
        
        self.logger.debug(f"Request completed: agent_id={agent_id}, method={method}, result_type={type(result)}")
        
        return result
    
    def get_connector_info(self) -> Dict[str, Any]:
        """
        Get information about loaded connectors and agent mappings.
        
        Returns:
            Dictionary containing connector and agent information
        """
        return {
            'loaded_connectors': list(self.loaded_connectors.keys()),
            'agent_mappings': {
                agent_id: connector_id 
                for agent_id, connector in self.agent_to_connector_map.items()
                for connector_id, conn_instance in self.loaded_connectors.items()
                if conn_instance == connector
            },
            'total_connectors': len(self.loaded_connectors),
            'total_agents': len(self.agent_to_connector_map)
        } 