"""
WxCC Gateway Server implementation.

This module implements the gRPC server that handles communication between
Webex Contact Center and the virtual agent connectors.
"""

import logging
import threading
import time
import uuid
from typing import Any, Dict, Iterator

import grpc
from src.generated import byova_common_pb2 as byova__common__pb2
from src.generated import voicevirtualagent_pb2 as voicevirtualagent__pb2
from src.generated import voicevirtualagent_pb2_grpc as voicevirtualagent__pb2_grpc
from .virtual_agent_router import VirtualAgentRouter


class WxCCGatewayServer(voicevirtualagent__pb2_grpc.VoiceVirtualAgentServicer):
    """
    WxCC Gateway Server implementation.

    This class implements the VoiceVirtualAgentServicer interface to handle
    gRPC requests from Webex Contact Center and route them to appropriate
    virtual agent connectors.
    """

    def __init__(self, router: VirtualAgentRouter, conversation_timeout: int = 300) -> None:
        """
        Initialize the WxCC Gateway Server.

        Args:
            router: VirtualAgentRouter instance for routing requests to connectors
            conversation_timeout: Timeout for conversations in seconds
        """
        self.router = router
        self.logger = logging.getLogger(__name__)

        # Conversation management - track active conversations by conversation_id
        self.active_conversations: Dict[str, Dict[str, Any]] = {}

        # Connection tracking for monitoring
        self.connection_events = []
        self.conversation_timeout = conversation_timeout  # 5 minutes default timeout
        self.conversation_cleanup_thread = None
        self.stop_cleanup = False

        # Start conversation cleanup thread
        self._start_conversation_cleanup_thread()

        self.logger.info(
            f"WxCCGatewayServer initialized with conversation timeout: {conversation_timeout}s"
        )

    def shutdown(self):
        """Gracefully shut down the server and cleanup threads."""
        self.logger.info("Shutting down WxCCGatewayServer...")
        self.stop_cleanup = True

        # Wait for cleanup thread to finish
        if self.conversation_cleanup_thread and self.conversation_cleanup_thread.is_alive():
            self.conversation_cleanup_thread.join(timeout=5)

        # Clean up all active conversations
        for conversation_id in list(self.active_conversations.keys()):
            self._cleanup_conversation(conversation_id)

        self.logger.info("WxCCGatewayServer shutdown complete")

    def _start_conversation_cleanup_thread(self):
        """Start background thread for conversation cleanup."""
        self.conversation_cleanup_thread = threading.Thread(
            target=self._conversation_cleanup_worker, daemon=True
        )
        self.conversation_cleanup_thread.start()
        self.logger.info("Conversation cleanup thread started")

    def _conversation_cleanup_worker(self):
        """Background worker to clean up expired conversations."""
        while not self.stop_cleanup:
            try:
                current_time = time.time()
                expired_conversations = []

                for conversation_id, conversation_data in self.active_conversations.items():
                    last_activity = conversation_data.get("last_activity", 0)
                    if current_time - last_activity > self.conversation_timeout:
                        expired_conversations.append(conversation_id)

                for conversation_id in expired_conversations:
                    self.logger.info(f"Cleaning up expired conversation {conversation_id}")
                    self._cleanup_conversation(conversation_id)

                time.sleep(60)  # Check every minute
            except Exception as e:
                self.logger.error(f"Error in conversation cleanup worker: {e}")
                time.sleep(60)

    def _cleanup_conversation(self, conversation_id: str):
        """Clean up a specific conversation."""
        if conversation_id in self.active_conversations:
            conversation_data = self.active_conversations[conversation_id]
            agent_id = conversation_data.get("agent_id")

            try:
                self.router.route_request(agent_id, "end_session", conversation_id)
                self.add_connection_event("end", conversation_id, agent_id, reason="timeout")
                self.logger.info(f"Cleaned up conversation {conversation_id}")
            except Exception as e:
                self.logger.warning(f"Error cleaning up conversation {conversation_id}: {e}")
            finally:
                del self.active_conversations[conversation_id]

    def _update_conversation_activity(self, conversation_id: str):
        """Update the last activity time for a conversation."""
        if conversation_id in self.active_conversations:
            self.active_conversations[conversation_id]["last_activity"] = time.time()

    def add_connection_event(
        self, event_type: str, conversation_id: str, agent_id: str, **kwargs
    ) -> None:
        """
        Add a connection event for monitoring.

        Args:
            event_type: Type of event (start, message, end)
            conversation_id: Conversation identifier
            agent_id: Agent identifier
            **kwargs: Additional event data
        """
        event = {
            "event_type": event_type,
            "conversation_id": conversation_id,
            "agent_id": agent_id,
            "timestamp": time.time(),
            **kwargs,
        }
        self.connection_events.append(event)

        # Keep only the last 100 events
        if len(self.connection_events) > 100:
            self.connection_events.pop(0)

        self.logger.debug(
            f"Added connection event: {event_type} for conversation {conversation_id}"
        )

    def get_connection_events(self) -> list:
        """
        Get connection events for monitoring.

        Returns:
            List of connection events
        """
        return self.connection_events.copy()

    def get_active_conversations(self) -> Dict[str, Dict[str, Any]]:
        """
        Get current active conversations for monitoring.

        Returns:
            Dictionary of active conversations
        """
        return self.active_conversations.copy()

    def end_conversation(self, conversation_id: str) -> None:
        """
        Manually end a conversation.

        Args:
            conversation_id: Conversation identifier to end
        """
        if conversation_id in self.active_conversations:
            conversation_data = self.active_conversations[conversation_id]
            agent_id = conversation_data.get("agent_id")

            try:
                self.router.route_request(agent_id, "end_session", conversation_id)
                self.add_connection_event("end", conversation_id, agent_id, reason="manual")
                self.logger.info(f"Manually ended conversation {conversation_id}")
            except Exception as e:
                self.logger.warning(f"Error ending conversation {conversation_id}: {e}")
            finally:
                del self.active_conversations[conversation_id]

    def ListVirtualAgents(
        self, request: byova__common__pb2.ListVARequest, context: grpc.ServicerContext
    ) -> byova__common__pb2.ListVAResponse:
        print("🔍 DEBUG: ListVirtualAgents called!")
        """
        List all available virtual agents.

        This method returns a list of all virtual agents that are available
        through the configured connectors.

        Args:
            request: ListVARequest containing customer org ID and other parameters
            context: gRPC context for the request

        Returns:
            ListVAResponse containing all available virtual agents
        """
        try:
            # Extract JWT token from metadata for authentication
            # TODO: Implement JWT validation logic here
            metadata = context.invocation_metadata()
            self.logger.debug(f"ListVirtualAgents called with metadata: {metadata}")

            # Get all available agents from the router
            available_agents = self.router.get_all_available_agents()

            # Build the response
            virtual_agents = []
            for i, agent_id in enumerate(available_agents):
                agent_info = byova__common__pb2.VirtualAgentInfo(
                    virtual_agent_id=agent_id,
                    virtual_agent_name=f"Local Audio Agent {i + 1}",  # More descriptive name
                    is_default=(i == 0),  # First agent is default
                    attributes={},  # TODO: Add agent-specific attributes
                )
                virtual_agents.append(agent_info)

            response = byova__common__pb2.ListVAResponse(virtual_agents=virtual_agents)

            self.logger.info(
                f"ListVirtualAgents: Returning {len(virtual_agents)} agents"
            )
            return response

        except Exception as e:
            self.logger.error(f"Error in ListVirtualAgents: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Internal server error: {str(e)}")
            return byova__common__pb2.ListVAResponse()

    def ProcessCallerInput(
        self,
        request_iterator: Iterator[voicevirtualagent__pb2.VoiceVARequest],
        context: grpc.ServicerContext,
    ) -> Iterator[voicevirtualagent__pb2.VoiceVAResponse]:
        """
        Process caller input in a bidirectional streaming RPC.

        This method handles real-time communication between the caller and
        virtual agent, processing audio, DTMF, and event inputs.

        Args:
            request_iterator: Iterator of VoiceVARequest messages
            context: gRPC context for the stream

        Yields:
            VoiceVAResponse messages containing agent responses
        """
        conversation_id = None
        agent_id = None
        rpc_session_id = str(uuid.uuid4())  # Unique identifier for this RPC session

        try:
            request_count = 0
            for request in request_iterator:
                request_count += 1
                # Debug: Print request information
                self.logger.info(
                    f"Received request #{request_count}: conversation_id={request.conversation_id}, agent_id={request.virtual_agent_id}, rpc_session_id={rpc_session_id}"
                )

                # Extract conversation and agent information from the first request
                if conversation_id is None:
                    conversation_id = request.conversation_id
                    agent_id = request.virtual_agent_id

                    # Use default agent if none specified
                    if not agent_id:
                        available_agents = self.router.get_all_available_agents()
                        if available_agents:
                            agent_id = available_agents[
                                0
                            ]  # Use first available agent as default
                            self.logger.info(
                                f"No agent_id specified, using default: {agent_id}"
                            )
                        else:
                            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                            context.set_details("No virtual agents available")
                            return

                    try:
                        # Verify agent exists
                        self.router.get_connector_for_agent(agent_id)
                    except ValueError:
                        context.set_code(grpc.StatusCode.NOT_FOUND)
                        context.set_details(f"Agent not found: {agent_id}")
                        return

                    self.logger.info(
                        f"Initializing conversation {conversation_id} with agent {agent_id} (RPC session: {rpc_session_id})"
                    )

                # Update conversation activity
                self._update_conversation_activity(conversation_id)

                # Convert gRPC request to connector format
                message_data = self._convert_grpc_request_to_connector_format(request)

                # Route the request to the appropriate connector
                try:
                    # For the first request in a conversation, call start_session
                    # Check if this is the first request by looking at the agent_id
                    is_first_request = bool(request.virtual_agent_id)
                    self.logger.debug(
                        f"Conversation {conversation_id}, agent_id: '{request.virtual_agent_id}', is_first_request: {is_first_request}, rpc_session: {rpc_session_id}"
                    )

                    # Check if this conversation has already sent the welcome message
                    conversation_sent_welcome = (
                        conversation_id in self.active_conversations
                        and self.active_conversations[conversation_id].get("welcome_sent", False)
                    )

                    if is_first_request and not conversation_sent_welcome:
                        # This is the first request - start the conversation
                        self.logger.debug(
                            f"Calling start_session for conversation {conversation_id} (RPC session: {rpc_session_id})"
                        )
                        connector_response = self.router.route_request(
                            agent_id, "start_session", conversation_id, message_data
                        )
                        self.logger.info(
                            f"Started conversation {conversation_id} with welcome message (RPC session: {rpc_session_id})"
                        )
                        self.logger.debug(
                            f"Start session response: {connector_response}"
                        )

                        # Add conversation to active conversations after successful start
                        self.active_conversations[conversation_id] = {
                            "agent_id": agent_id,
                            "conversation_id": conversation_id,
                            "customer_org_id": request.customer_org_id,
                            "welcome_sent": True,
                            "last_activity": time.time(),
                            "created_at": time.time(),
                            "rpc_sessions": [rpc_session_id],  # Track RPC sessions for this conversation
                        }

                        # Track connection event
                        self.add_connection_event(
                            "start",
                            conversation_id,
                            agent_id,
                            customer_org_id=request.customer_org_id,
                            rpc_session_id=rpc_session_id,
                        )
                    else:
                        # This is a subsequent request - send message
                        # Add this RPC session to the conversation's tracked sessions
                        if conversation_id in self.active_conversations:
                            rpc_sessions = self.active_conversations[conversation_id].get("rpc_sessions", [])
                            if rpc_session_id not in rpc_sessions:
                                rpc_sessions.append(rpc_session_id)
                                self.active_conversations[conversation_id]["rpc_sessions"] = rpc_sessions

                        self.logger.debug(
                            f"Calling send_message for conversation {conversation_id} (RPC session: {rpc_session_id})"
                        )
                        connector_response = self.router.route_request(
                            agent_id, "send_message", conversation_id, message_data
                        )
                        self.logger.debug(
                            f"Send message response: {connector_response}"
                        )

                        # Track message event
                        self.add_connection_event("message", conversation_id, agent_id, rpc_session_id=rpc_session_id)

                    # Convert connector response to gRPC format
                    grpc_response = self._convert_connector_response_to_grpc(
                        connector_response
                    )

                    # Only yield a response if there's actual content (prompts or output events)
                    if grpc_response.prompts or grpc_response.output_events:
                        yield grpc_response
                    else:
                        self.logger.debug(
                            f"No response content for conversation {conversation_id}, skipping response"
                        )

                except Exception as e:
                    self.logger.error(
                        f"Error processing request for conversation {conversation_id} (RPC session: {rpc_session_id}): {e}"
                    )
                    # Send error response
                    error_response = self._create_error_response(str(e))
                    yield error_response

        except Exception as e:
            self.logger.error(f"Error in ProcessCallerInput stream (RPC session: {rpc_session_id}): {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Stream error: {str(e)}")
        finally:
            # Don't immediately clean up the conversation when the stream ends
            # Let the background cleanup thread handle conversation expiration
            if conversation_id:
                self.logger.info(
                    f"RPC session {rpc_session_id} ended for conversation {conversation_id} (total requests: {request_count})"
                )
                # Update last activity to give the conversation some time to reconnect
                self._update_conversation_activity(conversation_id)
                self.logger.info(
                    f"Conversation {conversation_id} kept active for potential reconnection"
                )

    def _convert_grpc_request_to_connector_format(
        self, request: voicevirtualagent__pb2.VoiceVARequest
    ) -> Dict[str, Any]:
        """
        Convert gRPC request to connector format.

        Args:
            request: VoiceVARequest from gRPC

        Returns:
            Dictionary in connector format
        """
        message_data = {
            "conversation_id": request.conversation_id,
            "customer_org_id": request.customer_org_id,
            "virtual_agent_id": request.virtual_agent_id,
            "allow_partial_responses": request.allow_partial_responses,
            "vendor_specific_config": request.vendor_specific_config,
            "additional_info": dict(request.additional_info),
        }

        # Handle different input types
        if request.HasField("audio_input"):
            message_data["input_type"] = "audio"
            message_data["audio_data"] = {
                "caller_audio": request.audio_input.caller_audio,
                "encoding": request.audio_input.encoding,
                "sample_rate_hertz": request.audio_input.sample_rate_hertz,
                "language_code": request.audio_input.language_code,
                "is_single_utterance": request.audio_input.is_single_utterance,
            }
        elif request.HasField("dtmf_input"):
            message_data["input_type"] = "dtmf"
            message_data["dtmf_data"] = {
                "dtmf_events": list(request.dtmf_input.dtmf_events)
            }
        elif request.HasField("event_input"):
            message_data["input_type"] = "event"
            message_data["event_data"] = {
                "event_type": request.event_input.event_type,
                "name": request.event_input.name,
                "parameters": request.event_input.parameters,
            }

        return message_data

    def _convert_connector_response_to_grpc(
        self, connector_response: Dict[str, Any]
    ) -> voicevirtualagent__pb2.VoiceVAResponse:
        """
        Convert connector response to gRPC format.

        Args:
            connector_response: Response from connector

        Returns:
            VoiceVAResponse in gRPC format
        """
        try:
            self.logger.debug(f"Converting connector response: {connector_response}")

            # Handle empty or silence responses
            if (
                not connector_response
                or connector_response.get("message_type") == "silence"
            ):
                self.logger.debug("Returning empty response for silence")
                # Return empty response for silence
                return voicevirtualagent__pb2.VoiceVAResponse(
                    prompts=[],
                    output_events=[],
                    input_sensitive=False,
                    input_mode=voicevirtualagent__pb2.VoiceVAInputMode.INPUT_VOICE,
                    response_type=voicevirtualagent__pb2.VoiceVAResponse.ResponseType.PARTIAL,
                )

            # Create prompts
            prompts = []
            if connector_response.get("text"):
                # Disable barge-in for welcome messages to prevent interruption
                is_welcome = "welcome" in connector_response.get("text", "").lower()
                audio_content = connector_response.get("audio_content", b"")
                self.logger.debug(
                    f"Creating prompt with text: {connector_response.get('text')}, audio_content length: {len(audio_content)}"
                )

                prompt = voicevirtualagent__pb2.Prompt(
                    text=connector_response["text"],
                    audio_content=audio_content,
                    is_barge_in_enabled=not is_welcome,  # Disable barge-in for welcome messages
                )
                prompts.append(prompt)

            # Create output events
            output_events = []
            message_type = connector_response.get("message_type", "")

            if message_type == "goodbye":
                event = byova__common__pb2.OutputEvent(
                    event_type=byova__common__pb2.OutputEvent.EventType.SESSION_END,
                    name="session_ended",
                    metadata={},
                )
                output_events.append(event)
            elif message_type == "transfer":
                event = byova__common__pb2.OutputEvent(
                    event_type=byova__common__pb2.OutputEvent.EventType.TRANSFER_TO_AGENT,
                    name="transfer_requested",
                    metadata={},
                )
                output_events.append(event)

            # Create response
            response = voicevirtualagent__pb2.VoiceVAResponse(
                prompts=prompts,
                output_events=output_events,
                input_sensitive=False,
                input_mode=voicevirtualagent__pb2.VoiceVAInputMode.INPUT_VOICE,
                response_type=voicevirtualagent__pb2.VoiceVAResponse.ResponseType.PARTIAL,
            )

            self.logger.debug(
                f"Created gRPC response with {len(prompts)} prompts and {len(output_events)} events"
            )
            return response

        except Exception as e:
            self.logger.error(f"Error converting connector response to gRPC: {e}")
            self.logger.error(f"Connector response was: {connector_response}")
            # Return an error response
            return self._create_error_response(f"Failed to convert response: {str(e)}")

    def _create_error_response(
        self, error_message: str
    ) -> voicevirtualagent__pb2.VoiceVAResponse:
        """
        Create an error response.

        Args:
            error_message: Error message to include

        Returns:
            VoiceVAResponse with error information
        """
        prompt = voicevirtualagent__pb2.Prompt(
            text=f"I'm sorry, I encountered an error: {error_message}",
            is_barge_in_enabled=False,
        )

        event = byova__common__pb2.OutputEvent(
            event_type=byova__common__pb2.OutputEvent.EventType.CUSTOM_EVENT,
            name="error_occurred",
            metadata={},
        )

        response = voicevirtualagent__pb2.VoiceVAResponse(
            prompts=[prompt],
            output_events=[event],
            input_sensitive=False,
            input_mode=voicevirtualagent__pb2.VoiceVAInputMode.INPUT_VOICE,
            response_type=voicevirtualagent__pb2.VoiceVAResponse.ResponseType.FINAL,
        )

        return response
