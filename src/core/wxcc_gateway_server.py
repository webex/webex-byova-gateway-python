"""
WxCC Gateway Server implementation.

This module implements the gRPC server that handles communication between
Webex Contact Center and the virtual agent connectors.
"""

import logging
import time
from typing import Any, Dict, Iterator

import grpc

import voicevirtualagent_pb2 as voicevirtualagent__pb2
import voicevirtualagent_pb2_grpc as voicevirtualagent__pb2_grpc
import byova_common_pb2 as byova__common__pb2
from virtual_agent_router import VirtualAgentRouter


class WxCCGatewayServer(voicevirtualagent__pb2_grpc.VoiceVirtualAgentServicer):
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
        
        # Session management - simple dictionary mapping session IDs to context
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        
        # Connection tracking for monitoring
        self.connection_events = []
        
        self.logger.info("WxCCGatewayServer initialized")
    
    def add_connection_event(self, event_type: str, session_id: str, agent_id: str, **kwargs) -> None:
        """
        Add a connection event for monitoring.
        
        Args:
            event_type: Type of event (start, message, end)
            session_id: Session identifier
            agent_id: Agent identifier
            **kwargs: Additional event data
        """
        event = {
            'event_type': event_type,
            'session_id': session_id,
            'agent_id': agent_id,
            'timestamp': time.time(),
            **kwargs
        }
        self.connection_events.append(event)
        
        # Keep only last 100 events
        if len(self.connection_events) > 100:
            self.connection_events.pop(0)
    
    def get_connection_events(self) -> list:
        """
        Get recent connection events for monitoring.
        
        Returns:
            List of recent connection events
        """
        return self.connection_events.copy()
    
    def get_active_sessions(self) -> Dict[str, Dict[str, Any]]:
        """
        Get current active sessions for monitoring.
        
        Returns:
            Dictionary of active sessions
        """
        return self.active_sessions.copy()
    
    def end_session(self, session_id: str) -> None:
        """
        Manually end a session.
        
        Args:
            session_id: Session identifier to end
        """
        if session_id in self.active_sessions:
            session_data = self.active_sessions[session_id]
            agent_id = session_data.get('agent_id')
            
            try:
                self.router.route_request(agent_id, "end_session", session_id)
                self.add_connection_event('end', session_id, agent_id)
                self.logger.info(f"Manually ended session {session_id}")
            except Exception as e:
                self.logger.warning(f"Error ending session {session_id}: {e}")
            finally:
                del self.active_sessions[session_id]
    
    def ListVirtualAgents(self, request: byova__common__pb2.ListVARequest, 
                         context: grpc.ServicerContext) -> byova__common__pb2.ListVAResponse:
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
                    virtual_agent_name=f"Local Audio Agent {i+1}",  # More descriptive name
                    is_default=(i == 0),  # First agent is default
                    attributes={}  # TODO: Add agent-specific attributes
                )
                virtual_agents.append(agent_info)
            
            response = byova__common__pb2.ListVAResponse(
                virtual_agents=virtual_agents
            )
            
            self.logger.info(f"ListVirtualAgents: Returning {len(virtual_agents)} agents")
            return response
            
        except Exception as e:
            self.logger.error(f"Error in ListVirtualAgents: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Internal server error: {str(e)}")
            return byova__common__pb2.ListVAResponse()
    
    def ProcessCallerInput(self, request_iterator: Iterator[voicevirtualagent__pb2.VoiceVARequest],
                          context: grpc.ServicerContext) -> Iterator[voicevirtualagent__pb2.VoiceVAResponse]:
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
        session_id = None
        agent_id = None
        
        try:
            request_count = 0
            for request in request_iterator:
                request_count += 1
                # Debug: Print request information
                self.logger.info(f"Received request #{request_count}: conversation_id={request.conversation_id}, agent_id={request.virtual_agent_id}")
                
                # Extract session and agent information from the first request
                if session_id is None:
                    session_id = request.conversation_id
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
                    
                    try:
                        # Verify agent exists
                        self.router.get_connector_for_agent(agent_id)
                    except ValueError as e:
                        context.set_code(grpc.StatusCode.NOT_FOUND)
                        context.set_details(f"Agent not found: {agent_id}")
                        return
                    
                    self.logger.info(f"Initializing session {session_id} with agent {agent_id}")
                
                # Convert gRPC request to connector format
                message_data = self._convert_grpc_request_to_connector_format(request)
                
                # Route the request to the appropriate connector
                try:
                    # For the first request in a session, call start_session
                    # Check if this is the first request by looking at the agent_id
                    is_first_request = bool(request.virtual_agent_id)
                    self.logger.debug(f"Session {session_id}, agent_id: '{request.virtual_agent_id}', is_first_request: {is_first_request}")
                    
                    # Check if this session has already sent the welcome message
                    session_sent_welcome = session_id in self.active_sessions and self.active_sessions[session_id].get('welcome_sent', False)
                    
                    if is_first_request and not session_sent_welcome:
                        # This is the first request - start the session
                        self.logger.debug(f"Calling start_session for session {session_id}")
                        connector_response = self.router.route_request(
                            agent_id, 
                            "start_session", 
                            session_id, 
                            message_data
                        )
                        self.logger.info(f"Started session {session_id} with welcome message")
                        self.logger.debug(f"Start session response: {connector_response}")
                        
                        # Add session to active sessions after successful start
                        self.active_sessions[session_id] = {
                            'agent_id': agent_id,
                            'conversation_id': session_id,
                            'customer_org_id': request.customer_org_id,
                            'welcome_sent': True
                        }
                        
                        # Track connection event
                        self.add_connection_event('start', session_id, agent_id, 
                                               customer_org_id=request.customer_org_id)
                    else:
                        # This is a subsequent request - send message
                        self.logger.debug(f"Calling send_message for session {session_id}")
                        connector_response = self.router.route_request(
                            agent_id, 
                            "send_message", 
                            session_id, 
                            message_data
                        )
                        self.logger.debug(f"Send message response: {connector_response}")
                        
                        # Track message event
                        self.add_connection_event('message', session_id, agent_id)
                    
                    # Convert connector response to gRPC format
                    grpc_response = self._convert_connector_response_to_grpc(connector_response)
                    
                    yield grpc_response
                    
                except Exception as e:
                    self.logger.error(f"Error processing request for session {session_id}: {e}")
                    # Send error response
                    error_response = self._create_error_response(str(e))
                    yield error_response
                    
        except Exception as e:
            self.logger.error(f"Error in ProcessCallerInput stream: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Stream error: {str(e)}")
        finally:
            # Clean up session only if it's still active
            if session_id and session_id in self.active_sessions:
                self.logger.info(f"Stream ended, cleaning up session {session_id} (total requests: {request_count})")
                try:
                    self.router.route_request(agent_id, "end_session", session_id)
                    # Track session end event
                    self.add_connection_event('end', session_id, agent_id)
                    self.logger.info(f"Ended session {session_id}")
                except Exception as e:
                    self.logger.warning(f"Error ending session {session_id}: {e}")
                finally:
                    # Remove from active sessions
                    if session_id in self.active_sessions:
                        del self.active_sessions[session_id]
                        self.logger.info(f"Removed session {session_id} from active sessions")
            else:
                self.logger.info(f"Stream ended, no active session to clean up (session_id: {session_id})")
    
    def _convert_grpc_request_to_connector_format(self, request: voicevirtualagent__pb2.VoiceVARequest) -> Dict[str, Any]:
        """
        Convert gRPC request to connector format.
        
        Args:
            request: VoiceVARequest from gRPC
            
        Returns:
            Dictionary in connector format
        """
        message_data = {
            'conversation_id': request.conversation_id,
            'customer_org_id': request.customer_org_id,
            'virtual_agent_id': request.virtual_agent_id,
            'allow_partial_responses': request.allow_partial_responses,
            'vendor_specific_config': request.vendor_specific_config,
            'additional_info': dict(request.additional_info)
        }
        
        # Handle different input types
        if request.HasField('audio_input'):
            message_data['input_type'] = 'audio'
            message_data['audio_data'] = {
                'caller_audio': request.audio_input.caller_audio,
                'encoding': request.audio_input.encoding,
                'sample_rate_hertz': request.audio_input.sample_rate_hertz,
                'language_code': request.audio_input.language_code,
                'is_single_utterance': request.audio_input.is_single_utterance
            }
        elif request.HasField('dtmf_input'):
            message_data['input_type'] = 'dtmf'
            message_data['dtmf_data'] = {
                'dtmf_events': list(request.dtmf_input.dtmf_events)
            }
        elif request.HasField('event_input'):
            message_data['input_type'] = 'event'
            message_data['event_data'] = {
                'event_type': request.event_input.event_type,
                'name': request.event_input.name,
                'parameters': request.event_input.parameters
            }
        
        return message_data
    
    def _convert_connector_response_to_grpc(self, connector_response: Dict[str, Any]) -> voicevirtualagent__pb2.VoiceVAResponse:
        """
        Convert connector response to gRPC format.
        
        Args:
            connector_response: Response from connector
            
        Returns:
            VoiceVAResponse in gRPC format
        """
        # Create prompts
        prompts = []
        if 'text' in connector_response:
            # Disable barge-in for welcome messages to prevent interruption
            is_welcome = 'welcome' in connector_response.get('text', '').lower()
            prompt = voicevirtualagent__pb2.Prompt(
                text=connector_response['text'],
                audio_content=connector_response.get('audio_content', b''),
                is_barge_in_enabled=not is_welcome  # Disable barge-in for welcome messages
            )
            prompts.append(prompt)
        
        # Create output events
        output_events = []
        if connector_response.get('message_type') == 'goodbye':
            event = byova__common__pb2.OutputEvent(
                event_type=byova__common__pb2.OutputEvent.EventType.SESSION_END,
                name="session_ended",
                metadata={}
            )
            output_events.append(event)
        elif connector_response.get('message_type') == 'transfer':
            event = byova__common__pb2.OutputEvent(
                event_type=byova__common__pb2.OutputEvent.EventType.TRANSFER_TO_AGENT,
                name="transfer_requested",
                metadata={}
            )
            output_events.append(event)
        
        # Create response
        response = voicevirtualagent__pb2.VoiceVAResponse(
            prompts=prompts,
            output_events=output_events,
            input_sensitive=False,
            input_mode=voicevirtualagent__pb2.VoiceVAInputMode.INPUT_VOICE,
            response_type=voicevirtualagent__pb2.VoiceVAResponse.ResponseType.PARTIAL
        )
        
        return response
    
    def _create_error_response(self, error_message: str) -> voicevirtualagent__pb2.VoiceVAResponse:
        """
        Create an error response.
        
        Args:
            error_message: Error message to include
            
        Returns:
            VoiceVAResponse with error information
        """
        prompt = voicevirtualagent__pb2.Prompt(
            text=f"I'm sorry, I encountered an error: {error_message}",
            is_barge_in_enabled=False
        )
        
        event = byova__common__pb2.OutputEvent(
            event_type=byova__common__pb2.OutputEvent.EventType.CUSTOM_EVENT,
            name="error_occurred",
            metadata={}
        )
        
        response = voicevirtualagent__pb2.VoiceVAResponse(
            prompts=[prompt],
            output_events=[event],
            input_sensitive=False,
            input_mode=voicevirtualagent__pb2.VoiceVAInputMode.INPUT_VOICE,
            response_type=voicevirtualagent__pb2.VoiceVAResponse.ResponseType.FINAL
        )
        
        return response 