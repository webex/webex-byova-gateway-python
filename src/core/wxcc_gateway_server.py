"""
WxCC Gateway Server implementation.

This module implements the gRPC server that handles communication between
Webex Contact Center and the virtual agent connectors.
"""

import logging
import time
from typing import Any, Dict, Iterator

import grpc

from src.generated import byova_common_pb2 as byova__common__pb2
from src.generated.voicevirtualagent_pb2 import (
    Prompt,
    VoiceVAInputMode,
    VoiceVARequest,
    VoiceVAResponse,
)
from src.generated.voicevirtualagent_pb2_grpc import VoiceVirtualAgentServicer

from .virtual_agent_router import VirtualAgentRouter


class ConversationProcessor:
    """
    Handles individual conversation processing.

    This class manages the state and processing for a single conversation,
    similar to the AudioProcessor in the Webex example.
    """

    # Event type mapping for readable logging
    EVENT_TYPE_NAMES = {
        0: "UNSPECIFIED_INPUT",
        1: "SESSION_START",
        2: "SESSION_END",
        3: "NO_INPUT",
        4: "START_OF_DTMF",
        5: "CUSTOM_EVENT"
    }

    def __init__(self, conversation_id: str, virtual_agent_id: str, router: VirtualAgentRouter):
        self.conversation_id = conversation_id
        self.virtual_agent_id = virtual_agent_id
        self.router = router
        self.logger = logging.getLogger(f"{__name__}.ConversationProcessor.{conversation_id}")
        self.start_time = time.time()
        self.session_started = False
        self.can_be_deleted = False

        self.logger.info(f"Created conversation processor for {conversation_id} with agent {virtual_agent_id}")

    def process_request(self, request: VoiceVARequest) -> Iterator[VoiceVAResponse]:
        """
        Process a single request and yield responses.

        Args:
            request: The gRPC request to process

        Yields:
            VoiceVAResponse messages
        """
        try:
            # Process the request based on input type
            if request.HasField("audio_input"):
                yield from self._process_audio_input(request.audio_input)
            elif request.HasField("dtmf_input"):
                yield from self._process_dtmf_input(request.dtmf_input)
            elif request.HasField("event_input"):
                yield from self._process_event_input(request.event_input)
            else:
                self.logger.warning(f"Unknown input type for conversation {self.conversation_id}")

        except Exception as e:
            self.logger.error(f"Error processing request for conversation {self.conversation_id}: {e}")
            yield self._create_error_response(f"Processing error: {str(e)}")

    def _start_conversation(self) -> Iterator[VoiceVAResponse]:
        """Start the conversation."""
        try:
            # Convert request to connector format
            message_data = {
                "conversation_id": self.conversation_id,
                "virtual_agent_id": self.virtual_agent_id,
                "input_type": "conversation_start"
            }

            # Route to connector
            connector_response = self.router.route_request(
                self.virtual_agent_id, "start_conversation", self.conversation_id, message_data
            )

            # Convert response to gRPC format with FINAL response type and disabled barge-in for conversation start
            yield self._convert_connector_response_to_grpc(
                connector_response,
                response_type=VoiceVAResponse.ResponseType.FINAL,
                barge_in_enabled=True # Enable barge-in for conversation start (until server bug is resolved)
            )

        except Exception as e:
            self.logger.error(f"Error starting conversation for conversation {self.conversation_id}: {e}")
            yield self._create_error_response(f"Conversation start error: {str(e)}")

    def _process_audio_input(self, audio_input) -> Iterator[VoiceVAResponse]:
        """Process audio input."""
        try:
            # Convert request to connector format
            message_data = {
                "conversation_id": self.conversation_id,
                "virtual_agent_id": self.virtual_agent_id,
                "input_type": "audio",
                "audio_data": {
                    "caller_audio": audio_input.caller_audio,
                    "encoding": audio_input.encoding,
                    "sample_rate_hertz": audio_input.sample_rate_hertz,
                    "language_code": audio_input.language_code,
                    "is_single_utterance": audio_input.is_single_utterance,
                }
            }

            # Route to connector
            connector_response = self.router.route_request(
                self.virtual_agent_id, "send_message", self.conversation_id, message_data
            )

            # Convert response to gRPC format
            grpc_response = self._convert_connector_response_to_grpc(connector_response)
            if grpc_response is not None:
                yield grpc_response

        except Exception as e:
            self.logger.error(f"Error processing audio input for conversation {self.conversation_id}: {e}")
            yield self._create_error_response(f"Audio processing error: {str(e)}")

    def _process_dtmf_input(self, dtmf_input) -> Iterator[VoiceVAResponse]:
        """Process DTMF input."""
        try:
            # Convert request to connector format
            message_data = {
                "conversation_id": self.conversation_id,
                "virtual_agent_id": self.virtual_agent_id,
                "input_type": "dtmf",
                "dtmf_data": {
                    "dtmf_events": list(dtmf_input.dtmf_events),
                }
            }

            # Route to connector
            connector_response = self.router.route_request(
                self.virtual_agent_id, "send_message", self.conversation_id, message_data
            )

            # Convert response to gRPC format
            grpc_response = self._convert_connector_response_to_grpc(connector_response,
                                                                      response_type=VoiceVAResponse.ResponseType.FINAL)
            if grpc_response is not None:
                yield grpc_response

        except Exception as e:
            self.logger.error(f"Error processing DTMF input for conversation {self.conversation_id}: {e}")
            yield self._create_error_response(f"DTMF processing error: {str(e)}")

    def _process_event_input(self, event_input) -> Iterator[VoiceVAResponse]:
        """Process event input."""
        try:
            # Log the event input details with readable event type name
            event_type_name = self.EVENT_TYPE_NAMES.get(event_input.event_type, f"UNKNOWN({event_input.event_type})")
            self.logger.info(
                f"Received event input for conversation {self.conversation_id}: "
                f"event_type={event_type_name}, "
                f"name='{event_input.name}', "
                f"parameters={dict(event_input.parameters)}"
            )

            # Handle SESSION_START event explicitly
            if event_input.event_type == byova__common__pb2.EventInput.EventType.SESSION_START:
                if not self.session_started:
                    self.logger.info(f"Processing SESSION_START event for conversation {self.conversation_id}")
                    yield from self._start_conversation()
                    self.session_started = True
                else:
                    self.logger.warning(f"SESSION_START event received but session already started for conversation {self.conversation_id}")
                return

            # Handle other event types
            # Convert request to connector format
            message_data = {
                "conversation_id": self.conversation_id,
                "virtual_agent_id": self.virtual_agent_id,
                "input_type": "event",
                "event_data": {
                    "event_type": event_input.event_type,
                    "name": event_input.name,
                    "parameters": event_input.parameters,
                }
            }

            # Route to connector
            connector_response = self.router.route_request(
                self.virtual_agent_id, "send_message", self.conversation_id, message_data
            )

            # Convert response to gRPC format
            grpc_response = self._convert_connector_response_to_grpc(connector_response)
            if grpc_response is not None:
                yield grpc_response

        except Exception as e:
            self.logger.error(f"Error processing event input for conversation {self.conversation_id}: {e}")
            yield self._create_error_response(f"Event processing error: {str(e)}")

    def _convert_connector_response_to_grpc(self, connector_response: Dict[str, Any], response_type: VoiceVAResponse.ResponseType = None, barge_in_enabled: bool = None) -> VoiceVAResponse:
        """Convert connector response to gRPC format with optional response type and barge-in settings."""
        try:
            va_response = VoiceVAResponse()

            # Handle empty or silence responses
            if not connector_response or connector_response.get("message_type") == "silence":
                # For silence responses, only send a response if explicitly requested (e.g., for session start)
                # Otherwise, return None to indicate no response should be sent
                if response_type is not None:
                    final_response_type = response_type
                    va_response.response_type = final_response_type
                    va_response.input_mode = VoiceVAInputMode.INPUT_VOICE_DTMF
                    va_response.input_handling_config.CopyFrom(byova__common__pb2.InputHandlingConfig(
                        dtmf_config=byova__common__pb2.DTMFInputConfig(
                            dtmf_input_length=1,
                            inter_digit_timeout_msec=300,
                            termchar=byova__common__pb2.DTMFDigits.DTMF_DIGIT_POUND
                        ),
                        speech_timers=byova__common__pb2.InputSpeechTimers(
                            complete_timeout_msec=5000
                        )
                    ))
                    return va_response
                else:
                    # Return None to indicate no response should be sent for silence
                    return None

            # Create prompts
            if connector_response.get("text"):
                audio_content = connector_response.get("audio_content", b"")

                # Use specified barge-in setting, or fall back to connector response setting
                if barge_in_enabled is not None:
                    # Use the explicitly specified barge-in setting
                    final_barge_in_enabled = barge_in_enabled
                else:
                    # Use the barge-in setting from the connector response
                    final_barge_in_enabled = connector_response.get("barge_in_enabled", True)

                prompt = Prompt()
                prompt.text = connector_response["text"]
                prompt.audio_content = audio_content
                prompt.is_barge_in_enabled = final_barge_in_enabled
                va_response.prompts.append(prompt)

            # Create output events
            message_type = connector_response.get("message_type", "")

            if message_type == "goodbye":
                output_event = byova__common__pb2.OutputEvent()
                output_event.event_type = byova__common__pb2.OutputEvent.EventType.SESSION_END
                output_event.name = "session_ended"
                va_response.output_events.append(output_event)
                self.can_be_deleted = True
            elif message_type == "transfer":
                output_event = byova__common__pb2.OutputEvent()
                output_event.event_type = byova__common__pb2.OutputEvent.EventType.TRANSFER_TO_AGENT
                output_event.name = "transfer_requested"
                va_response.output_events.append(output_event)
                self.can_be_deleted = True

            # Set response type
            final_response_type = response_type if response_type is not None else VoiceVAResponse.ResponseType.PARTIAL
            va_response.response_type = final_response_type

            # Set input mode
            va_response.input_mode = VoiceVAInputMode.INPUT_VOICE_DTMF

            # Set input handling configuration
            va_response.input_handling_config.CopyFrom(byova__common__pb2.InputHandlingConfig(
                dtmf_config=byova__common__pb2.DTMFInputConfig(
                    dtmf_input_length=1,
                    inter_digit_timeout_msec=300,
                    termchar=byova__common__pb2.DTMFDigits.DTMF_DIGIT_POUND
                ),
                speech_timers=byova__common__pb2.InputSpeechTimers(
                    complete_timeout_msec=5000
                )
            ))

            return va_response

        except Exception as e:
            self.logger.error(f"Error converting connector response to gRPC: {e}")
            return self._create_error_response(f"Response conversion error: {str(e)}")

    def _create_error_response(self, error_message: str) -> VoiceVAResponse:
        """Create an error response."""
        va_response = VoiceVAResponse()

        # Create prompt
        prompt = Prompt()
        prompt.text = f"I'm sorry, I encountered an error: {error_message}"
        prompt.is_barge_in_enabled = False
        va_response.prompts.append(prompt)

        # Create output event
        output_event = byova__common__pb2.OutputEvent()
        output_event.event_type = byova__common__pb2.OutputEvent.EventType.CUSTOM_EVENT
        output_event.name = "error_occurred"
        va_response.output_events.append(output_event)

        # Set response type
        va_response.response_type = VoiceVAResponse.ResponseType.FINAL

        # Set input mode
        va_response.input_mode = VoiceVAInputMode.INPUT_VOICE_DTMF

        # Set input handling configuration
        va_response.input_handling_config.CopyFrom(byova__common__pb2.InputHandlingConfig(
            dtmf_config=byova__common__pb2.DTMFInputConfig(
                dtmf_input_length=1,
                inter_digit_timeout_msec=300,
                termchar=byova__common__pb2.DTMFDigits.DTMF_DIGIT_POUND
            ),
            speech_timers=byova__common__pb2.InputSpeechTimers(
                complete_timeout_msec=5000
            )
        ))

        self.logger.info(f"Sending error response for conversation {self.conversation_id}")
        return va_response

    def cleanup(self):
        """Clean up conversation resources."""
        try:
            # End the conversation with the connector
            message_data = {
                "conversation_id": self.conversation_id,
                "virtual_agent_id": self.virtual_agent_id,
                "input_type": "conversation_end"
            }
            self.router.route_request(
                self.virtual_agent_id, "end_conversation", self.conversation_id, message_data
            )
        except Exception as e:
            self.logger.error(f"Error cleaning up conversation {self.conversation_id}: {e}")

        duration = time.time() - self.start_time
        self.logger.info(f"Cleaned up conversation {self.conversation_id} (duration: {duration:.2f}s)")


class WxCCGatewayServer(VoiceVirtualAgentServicer):
    """
    WxCC Gateway Server implementation.

    This class implements the VoiceVirtualAgentServicer interface to handle
    gRPC requests from Webex Contact Center and route them to appropriate
    virtual agent connectors.
    """

    def __init__(self, router: VirtualAgentRouter) -> None:
        """
        Initialize the WxCC Gateway Server.

        Args:
            router: VirtualAgentRouter instance for routing requests to connectors
        """
        self.router = router
        self.logger = logging.getLogger(__name__)

        # Conversation state management - track active conversations by conversation_id
        self.conversations: Dict[str, ConversationProcessor] = {}

        # Connection tracking for monitoring
        self.connection_events = []

        self.logger.info("WxCCGatewayServer initialized")

    def shutdown(self):
        """Gracefully shut down the server and cleanup conversations."""
        self.logger.info("Shutting down WxCCGatewayServer...")

        # Clean up all active conversations
        for conversation_id in list(self.conversations.keys()):
            self._cleanup_conversation(conversation_id)

        self.logger.info("WxCCGatewayServer shutdown complete")

    def _cleanup_conversation(self, conversation_id: str):
        """Clean up a specific conversation."""
        if conversation_id in self.conversations:
            try:
                self.conversations[conversation_id].cleanup()
            except Exception as e:
                self.logger.warning(f"Error cleaning up conversation {conversation_id}: {e}")
            finally:
                del self.conversations[conversation_id]

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
        active_conversations = {}
        for conversation_id, processor in self.conversations.items():
            active_conversations[conversation_id] = {
                "agent_id": processor.virtual_agent_id,
                "conversation_id": processor.conversation_id,
                "session_started": processor.session_started,
                "can_be_deleted": processor.can_be_deleted,
                "start_time": processor.start_time,
            }
        return active_conversations

    def ListVirtualAgents(
        self, request: byova__common__pb2.ListVARequest, context: grpc.ServicerContext
    ) -> byova__common__pb2.ListVAResponse:
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
            self.logger.info("ListVirtualAgents called")

            # Get all available agents from the router
            available_agents = self.router.get_all_available_agents()

            # Build the response
            virtual_agents = []
            for i, agent_id in enumerate(available_agents):
                display_name = agent_id
                # The agent_id now includes the connector prefix (e.g., "aws_lex_connector: Bot Name")
                # Extract just the agent name for display
                if ": " in agent_id:
                    agent_id = agent_id.split(": ", 1)[1]
                else:
                    agent_id = agent_id

                agent_info = byova__common__pb2.VirtualAgentInfo(
                    virtual_agent_id=agent_id,
                    virtual_agent_name=display_name,
                    is_default=(i == 0),  # First agent is default
                    attributes={},
                )
                virtual_agents.append(agent_info)

            response = byova__common__pb2.ListVAResponse(virtual_agents=virtual_agents)

            self.logger.info(f"ListVirtualAgents: Returning {len(virtual_agents)} agents")
            return response

        except Exception as e:
            self.logger.error(f"Error in ListVirtualAgents: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Internal server error: {str(e)}")
            return byova__common__pb2.ListVAResponse()

    def ProcessCallerInput(
        self,
        request_iterator: Iterator[VoiceVARequest],
        context: grpc.ServicerContext,
    ) -> Iterator[VoiceVAResponse]:
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
        processor = None

        try:
            for request in request_iterator:
                # Extract conversation and agent information from the first request
                if conversation_id is None:
                    conversation_id = request.conversation_id
                    agent_id = request.virtual_agent_id

                    # Use default agent if none specified
                    if not agent_id:
                        available_agents = self.router.get_all_available_agents()
                        if available_agents:
                            agent_id = available_agents[0]  # Use first available agent as default
                            self.logger.info(f"No agent_id specified, using default: {agent_id}")
                        else:
                            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                            context.set_details("No virtual agents available")
                            return

                    # Verify agent exists
                    try:
                        self.router.get_connector_for_agent(agent_id)
                    except ValueError:
                        context.set_code(grpc.StatusCode.NOT_FOUND)
                        context.set_details(f"Agent not found: {agent_id}")
                        return

                    # Create or get conversation processor
                    if conversation_id not in self.conversations:
                        processor = ConversationProcessor(conversation_id, agent_id, self.router)
                        self.conversations[conversation_id] = processor
                        self.add_connection_event("start", conversation_id, agent_id)
                        self.logger.info(f"Created new conversation processor for {conversation_id}")
                    else:
                        processor = self.conversations[conversation_id]
                        self.logger.info(f"Using existing conversation processor for {conversation_id}")

                # Log the input type being processed
                if request.HasField("audio_input"):
                    self.logger.debug(f"Processing audio input for conversation {conversation_id}")
                elif request.HasField("dtmf_input"):
                    self.logger.debug(f"Processing DTMF input for conversation {conversation_id}")
                elif request.HasField("event_input"):
                    event_type_name = ConversationProcessor.EVENT_TYPE_NAMES.get(request.event_input.event_type, f"UNKNOWN({request.event_input.event_type})")
                    self.logger.info(f"Processing event input for conversation {conversation_id}: {event_type_name}")
                else:
                    self.logger.warning(f"Unknown input type for conversation {conversation_id}")

                # Process the request through the conversation processor
                self.logger.debug(f"Processing request for conversation {conversation_id}")
                self.logger.debug(f"Request: {request}")

                yield from processor.process_request(request)

                # Track message event
                self.add_connection_event("message", conversation_id, agent_id)

        except Exception as e:
            self.logger.error(f"Error in ProcessCallerInput stream: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Stream error: {str(e)}")
        finally:
            # Clean up conversation if it can be deleted
            if conversation_id and conversation_id in self.conversations:
                processor = self.conversations[conversation_id]
                if processor.can_be_deleted:
                    self.logger.info(f"Cleaning up completed conversation {conversation_id}")
                    self._cleanup_conversation(conversation_id)
                    self.add_connection_event("end", conversation_id, agent_id, reason="completed")
                else:
                    self.logger.info(f"Keeping conversation {conversation_id} active for potential reconnection")
