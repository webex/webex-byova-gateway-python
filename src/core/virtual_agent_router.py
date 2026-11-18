"""
Virtual Agent Router implementation.

This module provides routing functionality to manage multiple vendor connectors
and route requests to the appropriate connector based on agent ID.
"""

import importlib
import logging
from collections.abc import Collection
from typing import Any, Dict, List

from src.connectors.i_vendor_connector import IVendorConnector
from src.generated.byova_common_pb2 import DTMFDigits


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

        # Dictionary to map agent IDs to their connector names
        # Key: agent ID
        # Value: connector name (e.g., "local_audio_connector", "aws_lex_connector")
        self.agent_to_connector_name_map: Dict[str, str] = {}

        # Transport eligibility is recorded per agent so discovery and runtime
        # selection enforce the same connector capability boundary.
        self.agent_supported_transports: Dict[str, frozenset[str]] = {}

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

        connectors_config = config.get("connectors", {})

        for connector_id, connector_config in connectors_config.items():
            try:
                # Extract connector configuration
                class_name = connector_config.get("class")
                module_name = connector_config.get("module")
                connector_specific_config = connector_config.get("config", {})

                if not class_name or not module_name:
                    self.logger.error(
                        f"Missing 'class' or 'module' for connector {connector_id}"
                    )
                    continue

                # Dynamically import the connector class
                try:
                    module = importlib.import_module(f"src.{module_name}")
                    connector_class = getattr(module, class_name)
                except (ImportError, AttributeError) as e:
                    self.logger.error(
                        f"Failed to import {class_name} from {module_name}: {e}"
                    )
                    continue

                # Verify it's a valid connector
                if not issubclass(connector_class, IVendorConnector):
                    self.logger.error(
                        f"{class_name} does not inherit from IVendorConnector"
                    )
                    continue

                # Instantiate the connector
                connector_instance = connector_class(connector_specific_config)

                # Get available agents from this connector
                available_agents = connector_instance.get_available_agents()

                # Only load connectors that have agents
                if not available_agents:
                    self.logger.warning(
                        f"Connector '{connector_id}' has no agents configured, skipping"
                    )
                    continue

                supported_transports = self._resolve_supported_transports(
                    connector_id,
                    connector_instance,
                    connector_config.get("supported_transports"),
                )

                # Map each agent to this connector
                for agent_id in available_agents:
                    self.agent_to_connector_map[agent_id] = connector_instance
                    self.agent_to_connector_name_map[agent_id] = connector_id
                    self.agent_supported_transports[agent_id] = supported_transports
                    self.logger.info(
                        "Mapped agent '%s' to connector '%s' for transports %s",
                        agent_id,
                        connector_id,
                        sorted(supported_transports),
                    )

                # Store the connector instance
                self.loaded_connectors[connector_id] = connector_instance

                self.logger.info(
                    f"Successfully loaded connector '{connector_id}' ({class_name}) "
                    f"with {len(available_agents)} agents: {available_agents}"
                )

            except Exception as e:
                self.logger.error(f"Failed to load connector {connector_id}: {e}")
                continue

        self.logger.info(
            f"Router loaded {len(self.loaded_connectors)} connectors "
            f"with {len(self.agent_to_connector_map)} total agents"
        )

    @staticmethod
    def _normalize_transports(
        transports: Collection[str], *, connector_id: str
    ) -> frozenset[str]:
        """Validate a connector transport declaration against the allow-list."""
        if isinstance(transports, (str, bytes)):
            raise ValueError(
                f"Connector '{connector_id}' supported_transports must be a list"
            )
        normalized = frozenset(str(value).strip().lower() for value in transports)
        allowed = {"grpc", "websocket"}
        if not normalized or not normalized <= allowed:
            raise ValueError(
                f"Connector '{connector_id}' supported_transports must contain only "
                "grpc and/or websocket"
            )
        return normalized

    def _resolve_supported_transports(
        self,
        connector_id: str,
        connector: IVendorConnector,
        configured: Any,
    ) -> frozenset[str]:
        """Resolve an explicit deployment override or connector-safe default."""
        declared = (
            connector.get_supported_transports()
            if configured is None
            else configured
        )
        if not isinstance(declared, Collection):
            raise ValueError(
                f"Connector '{connector_id}' supported_transports must be a list"
            )
        return self._normalize_transports(declared, connector_id=connector_id)

    @staticmethod
    def _normalize_transport(transport: str) -> str:
        normalized = transport.strip().lower()
        if normalized not in {"grpc", "websocket"}:
            raise ValueError(f"Unsupported gateway transport: {transport!r}")
        return normalized

    def get_all_available_agents(self, transport: str | None = None) -> List[str]:
        """
        Get a list of all available virtual agent IDs.

        Args:
            transport: Optional gateway transport eligibility filter.

        Returns:
            List of all unique virtual agent IDs registered in the router
        """
        if transport is None:
            return list(self.agent_to_connector_map.keys())
        normalized = self._normalize_transport(transport)
        return [
            agent_id
            for agent_id in self.agent_to_connector_map
            if normalized in self.agent_supported_transports.get(
                agent_id, frozenset({"grpc"})
            )
        ]

    def get_agent_info_with_connector(self) -> List[Dict[str, str]]:
        """
        Get a list of all available agents with their connector information.

        Returns:
            List of dictionaries containing agent_id and connector_name
        """
        agent_info = []
        for agent_id, connector_name in self.agent_to_connector_name_map.items():
            agent_info.append({"agent_id": agent_id, "connector_name": connector_name})
        return agent_info

    def get_connector_for_agent(
        self, agent_id: str, transport: str | None = None
    ) -> IVendorConnector:
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
            raise ValueError(
                f"Agent '{agent_id}' not found. Available agents: {available_agents}"
            )

        if transport is not None:
            normalized = self._normalize_transport(transport)
            supported = self.agent_supported_transports.get(
                agent_id, frozenset({"grpc"})
            )
            if normalized not in supported:
                raise ValueError(
                    f"Agent '{agent_id}' does not support transport '{normalized}'"
                )

        return self.agent_to_connector_map[agent_id]

    def get_audio_delivery_mode(self, agent_id: str) -> str:
        """Get the connector's declared audio delivery capability."""
        return self.get_connector_for_agent(agent_id).get_audio_delivery_mode()

    def get_websocket_output_mode(self, agent_id: str) -> str:
        """Get the connector's WebSocket response framing capability."""
        connector = self.get_connector_for_agent(agent_id)
        capability = getattr(connector, "get_websocket_output_mode", None)
        mode = capability() if capability is not None else "raw_chunk"
        if mode not in {"raw_chunk", "wav_final"}:
            raise ValueError(
                f"Connector for agent '{agent_id}' returned invalid WebSocket "
                f"output mode: {mode!r}"
            )
        return mode

    def get_input_mode(self, agent_id: str, transport: str) -> str:
        """Get and validate a connector's transport-specific input mode."""
        normalized_transport = self._normalize_transport(transport)
        connector = self.get_connector_for_agent(
            agent_id, transport=normalized_transport
        )
        mode = connector.get_input_mode(normalized_transport)
        allowed = {
            "INPUT_VOICE_MODE_UNSPECIFIED",
            "INPUT_VOICE",
            "INPUT_EVENT_DTMF",
            "INPUT_VOICE_DTMF",
        }
        if mode not in allowed:
            raise ValueError(
                f"Connector for agent '{agent_id}' returned invalid input mode: "
                f"{mode!r}"
            )
        return mode

    def get_dtmf_input_config(
        self, agent_id: str, transport: str
    ) -> dict[str, Any]:
        """Get and validate a connector's transport-specific DTMF policy."""
        normalized_transport = self._normalize_transport(transport)
        connector = self.get_connector_for_agent(
            agent_id, transport=normalized_transport
        )
        config = connector.get_dtmf_input_config(normalized_transport)
        if not isinstance(config, dict):
            raise ValueError("Connector DTMF input config must be a mapping")
        length = config.get("dtmf_input_length")
        timeout = config.get("inter_digit_timeout_msec")
        termchar = config.get("termchar")
        if not isinstance(length, int) or not 1 <= length <= 64:
            raise ValueError("Connector DTMF input length must be from 1 to 64")
        if not isinstance(timeout, int) or not 1 <= timeout <= 60000:
            raise ValueError(
                "Connector DTMF inter-digit timeout must be from 1 to 60000 ms"
            )
        if not isinstance(termchar, str):
            raise ValueError("Connector DTMF terminator must be an enum name")
        try:
            DTMFDigits.Value(termchar)
        except ValueError as error:
            raise ValueError(
                f"Connector returned invalid DTMF terminator: {termchar!r}"
            ) from error
        return {
            "dtmf_input_length": length,
            "inter_digit_timeout_msec": timeout,
            "termchar": termchar,
        }

    def should_observe_speech_boundaries(
        self, agent_id: str, conversation_id: str
    ) -> bool:
        """Ask the connector whether gateway VAD should observe a frame."""
        return self.get_connector_for_agent(agent_id).should_observe_speech_boundaries(
            conversation_id
        )

    def should_cleanup_on_client_stream_end(self, agent_id: str) -> bool:
        """Return whether the connector opts into stream-end cleanup."""
        return self.get_connector_for_agent(
            agent_id
        ).should_cleanup_on_client_stream_end()

    def should_coalesce_speech_end_with_response(self, agent_id: str) -> bool:
        """Return whether END_OF_INPUT should share the connector response."""
        return self.get_connector_for_agent(
            agent_id
        ).should_coalesce_speech_end_with_response()

    def should_merge_speech_pauses(self, agent_id: str) -> bool:
        """Return whether the connector merges resumptions before turn flush."""
        return self.get_connector_for_agent(agent_id).should_merge_speech_pauses()

    def set_async_response_sink(
        self, agent_id: str, conversation_id: str, response_sink
    ) -> None:
        """Attach a live gateway sink for autonomous connector responses."""
        self.get_connector_for_agent(agent_id).set_async_response_sink(
            conversation_id, response_sink
        )

    def clear_async_response_sink(
        self, agent_id: str, conversation_id: str, response_sink
    ) -> None:
        """Detach a live gateway sink from an autonomous connector."""
        self.get_connector_for_agent(agent_id).clear_async_response_sink(
            conversation_id, response_sink
        )

    def set_input_acknowledgement_sink(
        self, agent_id: str, conversation_id: str, acknowledgement_sink
    ) -> None:
        """Attach a gateway sink for current caller-input acknowledgement."""
        self.get_connector_for_agent(agent_id).set_input_acknowledgement_sink(
            conversation_id, acknowledgement_sink
        )

    def clear_input_acknowledgement_sink(
        self, agent_id: str, conversation_id: str, acknowledgement_sink
    ) -> None:
        """Detach a gateway caller-input acknowledgement sink."""
        self.get_connector_for_agent(agent_id).clear_input_acknowledgement_sink(
            conversation_id, acknowledgement_sink
        )

    def route_request(self, agent_id: str, method: str, *args, **kwargs) -> Any:
        """
        Route a request to the appropriate connector.

        This is the primary entry point for the WxCC gRPC server to interact
        with connectors. It routes requests based on agent ID and method name.

        Args:
            agent_id: The virtual agent ID to route the request to
            method: The method to call on the connector (e.g., "start_conversation", "send_message", "end_conversation")
            *args: Positional arguments to pass to the method
            **kwargs: Keyword arguments to pass to the method

        Returns:
            The result from the connector method call

        Raises:
            ValueError: If the agent_id is not found
            AttributeError: If the method doesn't exist on the connector
        """
        self.logger.debug(
            f"Routing request: agent_id={agent_id}, method={method}, args={args}, kwargs={kwargs}"
        )

        # Get the appropriate connector
        connector = self.get_connector_for_agent(agent_id)

        # Verify the method exists
        if not hasattr(connector, method):
            available_methods = [
                attr for attr in dir(connector) if not attr.startswith("_")
            ]
            raise AttributeError(
                f"Method '{method}' not found on connector. Available methods: {available_methods}"
            )

        # Call the method on the connector
        method_func = getattr(connector, method)
        result = method_func(*args, **kwargs)

        self.logger.debug(
            f"Request completed: agent_id={agent_id}, method={method}, result_type={type(result)}"
        )

        return result

    def get_connector_info(self) -> Dict[str, Any]:
        """
        Get information about loaded connectors and agent mappings.

        Returns:
            Dictionary containing connector and agent information
        """
        return {
            "loaded_connectors": list(self.loaded_connectors.keys()),
            "agent_mappings": {
                agent_id: connector_id
                for agent_id, connector in self.agent_to_connector_map.items()
                for connector_id, conn_instance in self.loaded_connectors.items()
                if conn_instance == connector
            },
            "agent_to_connector_names": self.agent_to_connector_name_map,
            "total_connectors": len(self.loaded_connectors),
            "total_agents": len(self.agent_to_connector_map),
        }
