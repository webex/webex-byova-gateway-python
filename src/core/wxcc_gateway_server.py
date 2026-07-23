"""
WxCC Gateway Server implementation.

This module implements the gRPC server that handles communication between
Webex Contact Center and the virtual agent connectors.
"""

import logging
import threading
import time
from typing import Any, Dict, Iterator, Optional

import grpc

from src.generated.byova_common_pb2 import (
    DTMFDigits,
    DTMFInputConfig,
    EventInput,
    InputHandlingConfig,
    InputSpeechTimers,
    ListVARequest,
    ListVAResponse,
    OutputEvent,
    VirtualAgentInfo,
)
from src.generated.voicevirtualagent_pb2 import (
    Prompt,
    VoiceVAInputMode,
    VoiceVARequest,
    VoiceVAResponse,
)
from src.generated.voicevirtualagent_pb2_grpc import VoiceVirtualAgentServicer

from .virtual_agent_router import VirtualAgentRouter
from .health_service import HealthCheckService
from src.utils.audio_normalizer import normalize_wxcc_audio
from src.utils.silero_speech_boundary import SileroSpeechBoundaryObserver


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
        5: "CUSTOM_EVENT",
    }

    def __init__(
        self, conversation_id: str, virtual_agent_id: str, router: VirtualAgentRouter,
        vad_config: Optional[Dict[str, Any]] = None,
        max_terminal_playback_seconds: float = 30.0,
    ):
        self.conversation_id = conversation_id
        self.virtual_agent_id = virtual_agent_id
        self.router = router
        self.logger = logging.getLogger(
            f"{__name__}.ConversationProcessor.{conversation_id}"
        )
        self.start_time = time.time()
        self.session_started = False
        self.can_be_deleted = False
        self.max_terminal_playback_seconds = max(
            0.0, float(max_terminal_playback_seconds)
        )
        self._stream_cancel_event = threading.Event()
        vad_settings = vad_config or {}
        self.vad_fallback_sample_rate_hertz = vad_settings.get(
            "fallback_sample_rate_hertz", 8000
        )
        self.speech_boundary_observer = SileroSpeechBoundaryObserver(
            conversation_id,
            **{
                key: value
                for key, value in vad_settings.items()
                if key != "fallback_sample_rate_hertz"
            },
        )

        self.logger.info(
            f"Created conversation processor for {conversation_id} with agent {virtual_agent_id}"
        )

    def set_stream_cancel_event(self, cancel_event: threading.Event) -> None:
        """Attach the cancellation signal for the active WxCC request stream."""
        self._stream_cancel_event = cancel_event

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
                self.logger.warning(
                    f"Unknown input type for conversation {self.conversation_id}"
                )

        except Exception as e:
            self.logger.error(
                f"Error processing request for conversation {self.conversation_id}: {e}"
            )
            yield self._create_error_response(f"Processing error: {str(e)}")

    def _start_conversation(self) -> Iterator[VoiceVAResponse]:
        """Start the conversation."""
        try:
            # Convert request to connector format
            message_data = {
                "conversation_id": self.conversation_id,
                "virtual_agent_id": self.virtual_agent_id,
                "input_type": "conversation_start",
            }

            self.logger.debug(
                f"Starting conversation with message_data: {message_data}"
            )

            # Route to connector
            connector_response = self.router.route_request(
                self.virtual_agent_id,
                "start_conversation",
                self.conversation_id,
                message_data,
            )

            self.logger.debug(
                f"Start Conversation Connector response received for {self.conversation_id}"
            )
            self.logger.debug(f"Connector response type: {type(connector_response)}")
            is_iterator = hasattr(connector_response, "__iter__") and not isinstance(
                connector_response, (dict, str, bytes)
            )
            if is_iterator:
                yield from self._iter_grpc_connector_responses(
                    connector_response,
                    delay_terminal_after_audio=True,
                )
                return

            if isinstance(connector_response, dict):
                self.logger.debug(
                    f"Connector response keys: {list(connector_response.keys())}"
                )
                self.logger.debug(
                    f"Audio content present: {connector_response.get('audio_content') is not None}"
                )
                if connector_response.get("audio_content"):
                    self.logger.debug(
                        f"Audio content size: {len(connector_response.get('audio_content'))}"
                    )

            # Convert response to gRPC format with FINAL response type and disabled barge-in for conversation start
            grpc_response = self._convert_connector_response_to_grpc(
                connector_response,
                response_type=VoiceVAResponse.ResponseType.FINAL,
                barge_in_enabled=False,  # Enable barge-in for conversation start (until server bug is resolved)
            )

            self.logger.debug(
                f"Start Conversation Connector response converted to gRPC format for {self.conversation_id}"
            )
            self.logger.debug(f"Connector gRPC response created: {grpc_response}")
            if grpc_response and hasattr(grpc_response, "prompts"):
                self.logger.debug(
                    f"gRPC response has {len(grpc_response.prompts)} prompts"
                )

            yield grpc_response

        except Exception as e:
            self.logger.error(
                f"Error starting conversation for conversation {self.conversation_id}: {e}"
            )
            import traceback

            self.logger.error(f"Traceback: {traceback.format_exc()}")
            yield self._create_error_response(f"Conversation start error: {str(e)}")

    def _process_audio_input(self, audio_input) -> Iterator[VoiceVAResponse]:
        """Process audio input."""
        try:
            # Convert request to connector format
            message_data = {
                "conversation_id": self.conversation_id,
                "virtual_agent_id": self.virtual_agent_id,
                "input_type": "audio",
                "audio_data": audio_input.caller_audio,
                "audio_metadata": {
                    "encoding": audio_input.encoding,
                    "sample_rate_hertz": audio_input.sample_rate_hertz,
                    "language_code": audio_input.language_code,
                },
            }

            # Route to connector
            connector_response = self.router.route_request(
                self.virtual_agent_id,
                "send_message",
                self.conversation_id,
                message_data,
            )

            yield from self._iter_grpc_connector_responses(connector_response)

            if not self.router.should_observe_speech_boundaries(
                self.virtual_agent_id, self.conversation_id
            ):
                self.logger.debug(
                    "Skipping speech-boundary observation during DTMF input for "
                    "conversation %s",
                    self.conversation_id,
                )
                return

            frame = normalize_wxcc_audio(
                audio_input.caller_audio,
                audio_input.encoding,
                audio_input.sample_rate_hertz,
                fallback_sample_rate_hertz=self.vad_fallback_sample_rate_hertz,
            )
            for signal in self.speech_boundary_observer.observe(frame):
                event_type = "START_OF_INPUT" if signal.kind == "speech_started" else "END_OF_INPUT"
                self.logger.info(
                    "Silero VAD emitted %s (%s) for conversation %s",
                    signal.kind,
                    event_type,
                    self.conversation_id,
                )
                boundary_event = {
                    "event_type": event_type,
                    "name": "" if event_type == "START_OF_INPUT" else "end_of_input",
                }
                boundary_connector_response = {
                    "message_type": "silence",
                    "output_events": [boundary_event],
                }
                coalesce_speech_end = (
                    signal.kind == "speech_ended"
                    and self.router.should_coalesce_speech_end_with_response(
                        self.virtual_agent_id
                    )
                )

                if not coalesce_speech_end:
                    response = self._convert_connector_response_to_grpc(
                        boundary_connector_response
                    )
                    if response is not None:
                        yield response

                boundary_response = self.router.route_request(
                    self.virtual_agent_id,
                    "handle_speech_boundary",
                    self.conversation_id,
                    {
                        "conversation_id": self.conversation_id,
                        "virtual_agent_id": self.virtual_agent_id,
                        "input_type": "speech_boundary",
                        "speech_boundary": {"kind": signal.kind},
                    },
                )
                if coalesce_speech_end:
                    is_iterator = (
                        hasattr(boundary_response, "__iter__")
                        and not isinstance(boundary_response, (dict, str, bytes))
                    )
                    if is_iterator:
                        boundary_responses = list(boundary_response)
                    elif boundary_response is None:
                        boundary_responses = []
                    else:
                        boundary_responses = [boundary_response]

                    has_terminal_response = any(
                        isinstance(response, dict)
                        and response.get("message_type") in {"transfer", "session_end"}
                        for response in boundary_responses
                    )

                    if has_terminal_response:
                        self.logger.info(
                            "Emitting END_OF_INPUT before %d terminal connector "
                            "response(s) for conversation %s",
                            len(boundary_responses),
                            self.conversation_id,
                        )
                        response = self._convert_connector_response_to_grpc(
                            boundary_connector_response
                        )
                        if response is not None:
                            yield response
                        yield from self._iter_grpc_connector_responses(
                            boundary_responses,
                            delay_terminal_after_audio=True,
                        )
                    else:
                        self.logger.info(
                            "Emitting END_OF_INPUT before %d normal connector "
                            "response(s) for conversation %s",
                            len(boundary_responses),
                            self.conversation_id,
                        )
                        response = self._convert_connector_response_to_grpc(
                            boundary_connector_response
                        )
                        if response is not None:
                            yield response
                        yield from self._iter_grpc_connector_responses(
                            boundary_responses
                        )
                else:
                    yield from self._iter_grpc_connector_responses(
                        boundary_response, include_single_response=False
                    )

        except Exception as e:
            self.logger.error(
                f"Error processing audio input for conversation {self.conversation_id}: {e}"
            )
            yield self._create_error_response(f"Audio processing error: {str(e)}")

    def _iter_grpc_connector_responses(
        self,
        connector_response,
        *,
        include_single_response: bool = True,
        additional_output_event: Optional[Dict[str, Any]] = None,
        delay_terminal_after_audio: bool = False,
    ) -> Iterator[VoiceVAResponse]:
        """Convert a connector response or response iterator to gRPC responses."""
        is_iterator = hasattr(connector_response, "__iter__") and not isinstance(
            connector_response, (dict, str, bytes)
        )
        if not is_iterator and not include_single_response:
            return

        responses = connector_response if is_iterator else (connector_response,)
        pending_output_event = (
            dict(additional_output_event)
            if additional_output_event is not None
            else None
        )
        pending_playback_seconds = 0.0

        for response in responses:
            if response is None:
                self.logger.debug(
                    "Skipping None response for conversation %s", self.conversation_id
                )
                continue

            if (
                delay_terminal_after_audio
                and pending_playback_seconds > 0
                and isinstance(response, dict)
                and response.get("message_type") in {"transfer", "session_end"}
            ):
                self.logger.info(
                    "Delaying terminal response %.3f seconds for CES audio "
                    "playback in conversation %s",
                    min(
                        pending_playback_seconds,
                        self.max_terminal_playback_seconds,
                    ),
                    self.conversation_id,
                )
                wait_seconds = min(
                    pending_playback_seconds,
                    self.max_terminal_playback_seconds,
                )
                if pending_playback_seconds > wait_seconds:
                    self.logger.warning(
                        "Capped terminal playback wait from %.3f to %.3f seconds "
                        "for conversation %s",
                        pending_playback_seconds,
                        wait_seconds,
                        self.conversation_id,
                    )
                if self._stream_cancel_event.wait(wait_seconds):
                    self.logger.info(
                        "Suppressed delayed terminal response after stream "
                        "cancellation for conversation %s",
                        self.conversation_id,
                    )
                    return
                pending_playback_seconds = 0.0

            if pending_output_event is not None and isinstance(response, dict):
                response = dict(response)
                output_events = list(response.get("output_events", []))
                output_events.append(pending_output_event)
                response["output_events"] = output_events
                pending_output_event = None

            if delay_terminal_after_audio and isinstance(response, dict):
                pending_playback_seconds = self._wav_playback_seconds(
                    response.get("audio_content", b"")
                )

            grpc_response = self._convert_connector_response_to_grpc(response)
            if grpc_response is not None:
                yield grpc_response

    @staticmethod
    def _wav_playback_seconds(audio_content: bytes) -> float:
        """Return playback duration for the connector's canonical WAV shape."""
        if (
            not isinstance(audio_content, bytes)
            or len(audio_content) < 44
            or audio_content[:4] != b"RIFF"
            or audio_content[8:12] != b"WAVE"
            or audio_content[36:40] != b"data"
        ):
            return 0.0

        byte_rate = int.from_bytes(audio_content[28:32], "little")
        data_size = int.from_bytes(audio_content[40:44], "little")
        if byte_rate <= 0 or data_size <= 0:
            return 0.0
        return data_size / byte_rate

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
                },
            }

            # Route to connector
            connector_response = self.router.route_request(
                self.virtual_agent_id,
                "send_message",
                self.conversation_id,
                message_data,
            )

            # Handle the new yield pattern from connectors
            if hasattr(connector_response, "__iter__") and not isinstance(
                connector_response, (dict, str, bytes)
            ):
                # It's a generator/iterator, yield each response
                for response in connector_response:
                    if response is not None:  # Skip None responses
                        grpc_response = self._convert_connector_response_to_grpc(
                            response, response_type=VoiceVAResponse.ResponseType.FINAL
                        )
                        if grpc_response is not None:
                            yield grpc_response
                    else:
                        self.logger.debug(
                            f"Skipping None response for conversation {self.conversation_id}"
                        )
            else:
                # It's a single response (backward compatibility)
                if connector_response is not None:  # Skip None responses
                    grpc_response = self._convert_connector_response_to_grpc(
                        connector_response,
                        response_type=VoiceVAResponse.ResponseType.FINAL,
                    )
                    if grpc_response is not None:
                        yield grpc_response
                else:
                    self.logger.debug(
                        f"Skipping None response for conversation {self.conversation_id}"
                    )

        except Exception as e:
            self.logger.error(
                f"Error processing DTMF input for conversation {self.conversation_id}: {e}"
            )
            yield self._create_error_response(f"DTMF processing error: {str(e)}")

    def _process_event_input(self, event_input) -> Iterator[VoiceVAResponse]:
        """Process event input."""
        try:
            # Log the event input details with readable event type name
            event_type_name = self.EVENT_TYPE_NAMES.get(
                event_input.event_type, f"UNKNOWN({event_input.event_type})"
            )
            self.logger.debug(
                f"Received event input for conversation {self.conversation_id}: "
                f"event_type={event_type_name}, "
                f"name='{event_input.name}', "
                f"parameters={dict(event_input.parameters)}"
            )

            # Handle SESSION_START event explicitly
            if event_input.event_type == EventInput.EventType.SESSION_START:
                if not self.session_started:
                    self.logger.debug(
                        f"Processing SESSION_START event for conversation {self.conversation_id}"
                    )
                    yield from self._start_conversation()
                    self.session_started = True
                else:
                    self.logger.warning(
                        f"SESSION_START event received but session already started for conversation {self.conversation_id}"
                    )
                return

            # Handle SESSION_END event explicitly
            if event_input.event_type == EventInput.EventType.SESSION_END:
                self.logger.info(
                    f"Processing SESSION_END event for conversation {self.conversation_id}"
                )
                # Mark conversation for cleanup
                self.can_be_deleted = True

                # End conversation with connector
                try:
                    message_data = {
                        "conversation_id": self.conversation_id,
                        "virtual_agent_id": self.virtual_agent_id,
                        "input_type": "conversation_end",
                        "termination_reason": "client_session_end",
                    }

                    # Route to connector to end conversation
                    connector_response = self.router.route_request(
                        self.virtual_agent_id,
                        "end_conversation",
                        self.conversation_id,
                        message_data,
                    )

                    # If connector returns a response, convert and yield it
                    if connector_response:
                        if hasattr(connector_response, "__iter__") and not isinstance(
                            connector_response, (dict, str, bytes)
                        ):
                            # It's a generator/iterator, yield each response
                            for response in connector_response:
                                grpc_response = (
                                    self._convert_connector_response_to_grpc(response)
                                )
                                if grpc_response is not None:
                                    yield grpc_response
                        else:
                            # It's a single response (backward compatibility)
                            grpc_response = self._convert_connector_response_to_grpc(
                                connector_response
                            )
                            if grpc_response is not None:
                                yield grpc_response

                except Exception as e:
                    self.logger.warning(
                        f"Error ending conversation with connector for {self.conversation_id}: {e}"
                    )

                # Create a final response indicating session end
                va_response = VoiceVAResponse()
                va_response.response_type = VoiceVAResponse.ResponseType.FINAL

                # Add SESSION_END output event
                output_event = OutputEvent()
                output_event.event_type = OutputEvent.EventType.SESSION_END
                output_event.name = "session_ended_by_client"
                va_response.output_events.append(output_event)

                self.logger.info(
                    f"Sent SESSION_END event to WxCC for conversation {self.conversation_id} (client-initiated)"
                )
                yield va_response
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
                },
            }

            # Route to connector
            connector_response = self.router.route_request(
                self.virtual_agent_id,
                "send_message",
                self.conversation_id,
                message_data,
            )

            # Handle the new yield pattern from connectors
            if hasattr(connector_response, "__iter__") and not isinstance(
                connector_response, (dict, str, bytes)
            ):
                # It's a generator/iterator, yield each response
                for response in connector_response:
                    if response is not None:  # Skip None responses
                        grpc_response = self._convert_connector_response_to_grpc(
                            response
                        )
                        if grpc_response is not None:
                            yield grpc_response
                    else:
                        self.logger.debug(
                            f"Skipping None response for conversation {self.conversation_id}"
                        )
            else:
                # It's a single response (backward compatibility)
                if connector_response is not None:  # Skip None responses
                    grpc_response = self._convert_connector_response_to_grpc(
                        connector_response
                    )
                    if grpc_response is not None:
                        yield grpc_response
                else:
                    self.logger.debug(
                        f"Skipping None response for conversation {self.conversation_id}"
                    )

        except Exception as e:
            self.logger.error(
                f"Error processing event input for conversation {self.conversation_id}: {e}"
            )
            yield self._create_error_response(f"Event processing error: {str(e)}")

    def _convert_connector_response_to_grpc(
        self,
        connector_response: Optional[Dict[str, Any]],
        response_type: VoiceVAResponse.ResponseType = None,
        barge_in_enabled: bool = None,
    ) -> Optional[VoiceVAResponse]:
        """Convert connector response to gRPC format with optional response type and barge-in settings."""
        try:
            # Handle None input
            if connector_response is None:
                self.logger.debug(
                    f"Received None response for conversation {self.conversation_id}"
                )
                return None

            self.logger.debug(
                f"Converting connector response to gRPC format for {self.conversation_id}"
            )
            self.logger.debug(f"Connector response: {connector_response}")

            va_response = VoiceVAResponse()

            # Handle empty or silence responses
            if (
                not connector_response
                or connector_response.get("message_type") == "silence"
            ):
                self.logger.debug("Handling silence/empty response")

                # Check if this is a START_OF_INPUT event
                has_start_event = False
                if connector_response is not None:
                    has_start_event = any(
                        event.get("event_type") == "START_OF_INPUT"
                        for event in connector_response.get("output_events", [])
                    )

                # Always set input_handling_config as it's mandatory in the protobuf
                # For START_OF_INPUT events, we'll set minimal config to satisfy the requirement
                if has_start_event:
                    self.logger.debug(
                        "Detected START_OF_INPUT event, setting minimal input_handling_config"
                    )
                    # Set minimal input_handling_config for START_OF_INPUT events
                    va_response.input_handling_config.CopyFrom(
                        InputHandlingConfig(
                            dtmf_config=DTMFInputConfig(
                                dtmf_input_length=1,
                                inter_digit_timeout_msec=300,
                                termchar=DTMFDigits.DTMF_DIGIT_POUND,
                            ),
                            speech_timers=InputSpeechTimers(complete_timeout_msec=5000),
                        )
                    )
                else:
                    # For regular silence responses, use specified response type or default to FINAL
                    final_response_type = (
                        response_type
                        if response_type is not None
                        else VoiceVAResponse.ResponseType.FINAL
                    )
                    va_response.response_type = final_response_type
                    va_response.input_mode = VoiceVAInputMode.INPUT_VOICE_DTMF
                    va_response.input_handling_config.CopyFrom(
                        InputHandlingConfig(
                            dtmf_config=DTMFInputConfig(
                                dtmf_input_length=1,
                                inter_digit_timeout_msec=300,
                                termchar=DTMFDigits.DTMF_DIGIT_POUND,
                            ),
                            speech_timers=InputSpeechTimers(complete_timeout_msec=5000),
                        )
                    )

                # Handle output events for silence responses before returning
                if connector_response and "output_events" in connector_response:
                    for event in connector_response["output_events"]:
                        event_type = event.get("event_type")
                        if event_type in [
                            "START_OF_INPUT",
                            "END_OF_INPUT",
                            "NO_MATCH",
                            "NO_INPUT",
                            "CUSTOM_EVENT",
                        ]:
                            output_event = OutputEvent()

                            # Convert event_type string to protobuf enum
                            if event_type == "END_OF_INPUT":
                                output_event.event_type = (
                                    OutputEvent.EventType.END_OF_INPUT
                                )
                            elif event_type == "START_OF_INPUT":
                                output_event.event_type = (
                                    OutputEvent.EventType.START_OF_INPUT
                                )
                            elif event_type == "NO_MATCH":
                                output_event.event_type = OutputEvent.EventType.NO_MATCH
                            elif event_type == "NO_INPUT":
                                output_event.event_type = OutputEvent.EventType.NO_INPUT
                            elif event_type == "CUSTOM_EVENT":
                                output_event.event_type = (
                                    OutputEvent.EventType.CUSTOM_EVENT
                                )

                            # Set event name
                            output_event.name = event.get("name", "")

                            # Convert metadata dict to google.protobuf.Struct if present
                            if event.get("metadata"):
                                try:
                                    from google.protobuf import struct_pb2

                                    metadata_struct = struct_pb2.Struct()
                                    metadata_struct.update(event["metadata"])
                                    output_event.metadata.CopyFrom(metadata_struct)
                                except Exception as e:
                                    self.logger.warning(
                                        f"Failed to convert metadata for event {event_type}: {e}"
                                    )

                            va_response.output_events.append(output_event)
                            self.logger.info(
                                f"Sent {event_type} event to WxCC for conversation {self.conversation_id}"
                            )
                            self.logger.debug(
                                f"Added {event_type} event to silence response"
                            )

                return va_response

            # Create prompts
            audio_content = connector_response.get("audio_content")
            self.logger.debug(
                f"Audio content present: {audio_content is not None}, size: {len(audio_content) if audio_content else 0}"
            )

            if audio_content:
                # Use specified barge-in setting, or fall back to connector response setting
                if barge_in_enabled is not None:
                    # Use the explicitly specified barge-in setting
                    final_barge_in_enabled = barge_in_enabled
                else:
                    # Use the barge-in setting from the connector response
                    final_barge_in_enabled = connector_response.get(
                        "barge_in_enabled", True
                    )

                self.logger.debug(
                    f"Creating prompt with audio content, barge_in_enabled: {final_barge_in_enabled}"
                )
                prompt = Prompt()
                prompt.text = connector_response["text"]
                prompt.audio_content = audio_content
                prompt.is_barge_in_enabled = final_barge_in_enabled
                va_response.prompts.append(prompt)
            else:
                # For responses without audio content, still create a text prompt
                # This is important for session_end and transfer responses
                if connector_response.get("text"):
                    self.logger.debug("Creating text-only prompt")
                    prompt = Prompt()
                    prompt.text = connector_response["text"]
                    prompt.is_barge_in_enabled = connector_response.get(
                        "barge_in_enabled", False
                    )
                    va_response.prompts.append(prompt)
                else:
                    self.logger.warning(
                        "No audio content or text found in connector response"
                    )

            # Create output events
            message_type = connector_response.get("message_type", "")

            if message_type == "goodbye":
                output_event = OutputEvent()
                output_event.event_type = OutputEvent.EventType.SESSION_END
                output_event.name = "session_ended"
                va_response.output_events.append(output_event)
                self.logger.info(
                    f"Sent SESSION_END event to WxCC for conversation {self.conversation_id} (goodbye message)"
                )
                self.can_be_deleted = True
            elif message_type == "transfer":
                output_event = OutputEvent()
                output_event.event_type = OutputEvent.EventType.TRANSFER_TO_AGENT
                output_event.name = "transfer_requested"
                va_response.output_events.append(output_event)
                self.logger.info(
                    f"Sent TRANSFER_TO_AGENT event to WxCC for conversation {self.conversation_id}"
                )
                self.can_be_deleted = True
            elif message_type == "session_end":
                output_event = OutputEvent()
                output_event.event_type = OutputEvent.EventType.SESSION_END
                output_event.name = "session_ended"
                va_response.output_events.append(output_event)
                self.logger.info(
                    f"Sent SESSION_END event to WxCC for conversation {self.conversation_id} (session_end message)"
                )
                self.can_be_deleted = True

            # Handle generic output events from connector responses
            if "output_events" in connector_response:
                for event in connector_response["output_events"]:
                    event_type = event.get("event_type")
                    if event_type in [
                        "START_OF_INPUT",
                        "END_OF_INPUT",
                        "NO_MATCH",
                        "NO_INPUT",
                        "CUSTOM_EVENT",
                        "SESSION_END",
                        "TRANSFER_TO_AGENT",
                    ]:
                        output_event = OutputEvent()

                        # Convert event_type string to protobuf enum
                        if event_type == "END_OF_INPUT":
                            output_event.event_type = OutputEvent.EventType.END_OF_INPUT
                        elif event_type == "START_OF_INPUT":
                            output_event.event_type = (
                                OutputEvent.EventType.START_OF_INPUT
                            )
                        elif event_type == "NO_MATCH":
                            output_event.event_type = OutputEvent.EventType.NO_MATCH
                        elif event_type == "NO_INPUT":
                            output_event.event_type = OutputEvent.EventType.NO_INPUT
                        elif event_type == "CUSTOM_EVENT":
                            output_event.event_type = OutputEvent.EventType.CUSTOM_EVENT
                        elif event_type == "SESSION_END":
                            output_event.event_type = OutputEvent.EventType.SESSION_END
                        elif event_type == "TRANSFER_TO_AGENT":
                            output_event.event_type = (
                                OutputEvent.EventType.TRANSFER_TO_AGENT
                            )

                        # Set event name
                        output_event.name = event.get("name", "")

                        # Convert metadata dict to google.protobuf.Struct if present
                        if event.get("metadata"):
                            try:
                                from google.protobuf import struct_pb2

                                metadata_struct = struct_pb2.Struct()
                                metadata_struct.update(event["metadata"])
                                output_event.metadata.CopyFrom(metadata_struct)
                            except Exception as e:
                                self.logger.warning(
                                    f"Failed to convert metadata for event {event_type}: {e}"
                                )

                        va_response.output_events.append(output_event)
                        self.logger.info(
                            f"Sent {event_type} event to WxCC for conversation {self.conversation_id}"
                        )
                        self.logger.debug(f"Added {event_type} event to gRPC response")

            # Set response type
            if response_type is not None:
                va_response.response_type = response_type
            elif connector_response and "response_type" in connector_response:
                # Convert string response type from connector to protobuf enum
                response_type_str = connector_response["response_type"]
                if response_type_str == "final":
                    va_response.response_type = VoiceVAResponse.ResponseType.FINAL
                elif response_type_str == "partial":
                    va_response.response_type = VoiceVAResponse.ResponseType.PARTIAL
                elif response_type_str == "chunk":
                    va_response.response_type = VoiceVAResponse.ResponseType.CHUNK
                else:
                    self.logger.warning(
                        f"Unknown response_type '{response_type_str}', defaulting to FINAL"
                    )
                    va_response.response_type = VoiceVAResponse.ResponseType.FINAL
            else:
                va_response.response_type = VoiceVAResponse.ResponseType.FINAL

            has_session_end_event = any(
                event.event_type == OutputEvent.EventType.SESSION_END
                for event in va_response.output_events
            )
            if has_session_end_event:
                # A server-originated SESSION_END is a terminal-only response.
                # Do not also tell WxCC to collect another voice/DTMF turn.
                # This matches Cisco's BYOVA reference response shape.
                self.can_be_deleted = True
            else:
                # Set the next input mode and handling configuration only while
                # the virtual-agent session is still active.
                va_response.input_mode = VoiceVAInputMode.INPUT_VOICE_DTMF
                va_response.input_handling_config.CopyFrom(
                    InputHandlingConfig(
                        dtmf_config=DTMFInputConfig(
                            dtmf_input_length=1,
                            inter_digit_timeout_msec=300,
                            termchar=DTMFDigits.DTMF_DIGIT_POUND,
                        ),
                        speech_timers=InputSpeechTimers(complete_timeout_msec=5000),
                    )
                )

            self.logger.debug(
                f"Final gRPC response created with {len(va_response.prompts)} prompts"
            )
            return va_response

        except Exception as e:
            self.logger.error(f"Error converting connector response to gRPC: {e}")
            import traceback

            self.logger.error(f"Traceback: {traceback.format_exc()}")
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
        output_event = OutputEvent()
        output_event.event_type = OutputEvent.EventType.CUSTOM_EVENT
        output_event.name = "error_occurred"
        va_response.output_events.append(output_event)
        self.logger.info(
            f"Sent CUSTOM_EVENT (error_occurred) to WxCC for conversation {self.conversation_id}"
        )

        # Set response type
        va_response.response_type = VoiceVAResponse.ResponseType.FINAL

        # Set input mode
        va_response.input_mode = VoiceVAInputMode.INPUT_VOICE_DTMF

        # Set input handling configuration
        va_response.input_handling_config.CopyFrom(
            InputHandlingConfig(
                dtmf_config=DTMFInputConfig(
                    dtmf_input_length=1,
                    inter_digit_timeout_msec=300,
                    termchar=DTMFDigits.DTMF_DIGIT_POUND,
                ),
                speech_timers=InputSpeechTimers(complete_timeout_msec=5000),
            )
        )

        self.logger.debug(
            f"Sending error response for conversation {self.conversation_id}"
        )
        return va_response

    def cleanup(self, termination_reason: str = "gateway_cleanup"):
        """Clean up conversation resources with a lifecycle reason."""
        try:
            # End the conversation with the connector
            message_data = {
                "conversation_id": self.conversation_id,
                "virtual_agent_id": self.virtual_agent_id,
                "input_type": "conversation_end",
                "termination_reason": termination_reason,
            }
            self.router.route_request(
                self.virtual_agent_id,
                "end_conversation",
                self.conversation_id,
                message_data,
            )
        except Exception as e:
            self.logger.error(
                f"Error cleaning up conversation {self.conversation_id}: {e}"
            )

        duration = time.time() - self.start_time
        self.logger.debug(
            f"Cleaned up conversation {self.conversation_id} (duration: {duration:.2f}s)"
        )


class WxCCGatewayServer(VoiceVirtualAgentServicer):
    """
    WxCC Gateway Server implementation.

    This class implements the VoiceVirtualAgentServicer interface to handle
    gRPC requests from Webex Contact Center and route them to appropriate
    virtual agent connectors.
    """

    def __init__(
        self,
        router: VirtualAgentRouter,
        vad_config: Optional[Dict[str, Any]] = None,
        max_terminal_playback_seconds: float = 30.0,
    ) -> None:
        """
        Initialize the WxCC Gateway Server.

        Args:
            router: VirtualAgentRouter instance for routing requests to connectors
            vad_config: Gateway-owned voice activity detection settings.
        """
        self.router = router
        self.vad_config = vad_config or {}
        self.max_terminal_playback_seconds = max_terminal_playback_seconds
        self.logger = logging.getLogger(__name__)

        # Conversation state management - track active conversations by conversation_id
        self.conversations: Dict[str, ConversationProcessor] = {}

        # Connection tracking for monitoring
        self.connection_events = []

        # Health check service with router for real health monitoring
        self.health_service = HealthCheckService(self.router)

        self.logger.info("WxCCGatewayServer initialized")

    def shutdown(self):
        """Gracefully shut down the server and cleanup conversations."""
        self.logger.info("Shutting down WxCCGatewayServer...")

        # Clean up all active conversations
        for conversation_id in list(self.conversations.keys()):
            self._cleanup_conversation(
                conversation_id, termination_reason="gateway_shutdown"
            )

        self.logger.info("WxCCGatewayServer shutdown complete")

    def _cleanup_conversation(
        self, conversation_id: str, termination_reason: str = "gateway_cleanup"
    ):
        """Clean up a specific conversation."""
        if conversation_id in self.conversations:
            try:
                self.conversations[conversation_id].cleanup(termination_reason)
            except Exception as e:
                self.logger.warning(
                    f"Error cleaning up conversation {conversation_id}: {e}"
                )
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

    def get_health_status(self) -> Dict[str, Any]:
        """Get basic health status."""
        return self.health_service.get_overall_health()

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
        self, request: ListVARequest, context: grpc.ServicerContext
    ) -> ListVAResponse:
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
            self.logger.debug("ListVirtualAgents called")

            # Get all available agents from the router
            available_agents = self.router.get_all_available_agents()

            # Build the response
            virtual_agents = []
            for i, full_agent_id in enumerate(available_agents):
                # The full_agent_id includes the connector prefix (e.g., "aws_lex_connector: Bot Name")
                # Extract just the agent name for display
                if ": " in full_agent_id:
                    agent_name = full_agent_id.split(": ", 1)[1]
                else:
                    agent_name = full_agent_id

                agent_info = VirtualAgentInfo(
                    virtual_agent_id=full_agent_id,  # Use the full agent ID for routing
                    virtual_agent_name=agent_name,  # Use the extracted name for display
                    is_default=(i == 0),  # First agent is default
                    attributes={},
                )
                virtual_agents.append(agent_info)

            response = ListVAResponse(virtual_agents=virtual_agents)

            self.logger.debug(
                f"ListVirtualAgents: Returning {len(virtual_agents)} agents"
            )
            return response

        except Exception as e:
            self.logger.error(f"Error in ListVirtualAgents: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Internal server error: {str(e)}")
            return ListVAResponse()

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
        stream_end_reason = "client_half_close"
        stream_cancel_event = threading.Event()
        if context:
            context.add_callback(stream_cancel_event.set)

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
                            agent_id = available_agents[
                                0
                            ]  # Use first available agent as default
                            self.logger.debug(
                                f"No agent_id specified, using default: {agent_id}"
                            )
                        else:
                            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                            context.set_details("No virtual agents available")
                            return

                    # Verify agent exists
                    try:
                        self.router.get_connector_for_agent(agent_id)
                    except ValueError:
                        self.logger.error(f"Agent not found: {agent_id}")
                        context.set_code(grpc.StatusCode.NOT_FOUND)
                        context.set_details(f"Agent not found: {agent_id}")
                        return

                    # Create or get conversation processor
                    if conversation_id not in self.conversations:
                        processor = ConversationProcessor(
                            conversation_id,
                            agent_id,
                            self.router,
                            self.vad_config,
                            self.max_terminal_playback_seconds,
                        )
                        self.conversations[conversation_id] = processor
                        self.add_connection_event("start", conversation_id, agent_id)
                        self.logger.debug(
                            f"Created new conversation processor for {conversation_id}"
                        )
                    else:
                        processor = self.conversations[conversation_id]
                        if processor.virtual_agent_id != agent_id:
                            self.logger.error(
                                "Rejected conversation %s reconnection with agent %s; "
                                "existing agent is %s",
                                conversation_id,
                                agent_id,
                                processor.virtual_agent_id,
                            )
                            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                            context.set_details(
                                "virtual_agent_id does not match the existing "
                                "conversation"
                            )
                            return
                        agent_id = processor.virtual_agent_id
                        self.logger.debug(
                            f"Using existing conversation processor for {conversation_id}"
                        )

                    processor.set_stream_cancel_event(stream_cancel_event)

                # Log the input type being processed
                if request.HasField("audio_input"):
                    self.logger.debug(
                        f"Processing audio input for conversation {conversation_id}"
                    )
                elif request.HasField("dtmf_input"):
                    self.logger.debug(
                        f"Processing DTMF input for conversation {conversation_id}"
                    )
                elif request.HasField("event_input"):
                    event_type_name = ConversationProcessor.EVENT_TYPE_NAMES.get(
                        request.event_input.event_type,
                        f"UNKNOWN({request.event_input.event_type})",
                    )
                    self.logger.debug(
                        f"Processing event input for conversation {conversation_id}: {event_type_name}"
                    )
                else:
                    self.logger.warning(
                        f"Unknown input type for conversation {conversation_id}"
                    )

                # Process the request through the conversation processor
                self.logger.debug(
                    f"Processing request for conversation {conversation_id}"
                )
                self.logger.debug(f"Request: {request}")

                yield from processor.process_request(request)

                # Track message event
                self.add_connection_event("message", conversation_id, agent_id)

                if processor.can_be_deleted:
                    stream_end_reason = "server_terminal"
                    self.logger.info(
                        "Completing WxCC response stream after terminal response "
                        "for conversation %s",
                        conversation_id,
                    )
                    break

        except grpc.RpcError as e:
            if e.code() == grpc.StatusCode.CANCELLED:
                stream_end_reason = "client_cancelled"
            else:
                stream_end_reason = "stream_error"
                self.logger.error(f"Error in ProcessCallerInput stream: {e}")
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details(f"Stream error: {str(e)}")
        except Exception as e:
            stream_end_reason = "stream_error"
            self.logger.error(f"Error in ProcessCallerInput stream: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Stream error: {str(e)}")
        finally:
            stream_cancel_event.set()
            if context and not context.is_active():
                stream_end_reason = "client_cancelled"

            # WxCC normally half-closes one request RPC and reconnects with the
            # same conversation ID for subsequent caller input. Preserve the
            # processor and vendor session across that continuation boundary.
            # Connector opt-in applies only to cancellation and actual request
            # stream failures, where no continuation is expected.
            if conversation_id and conversation_id in self.conversations:
                processor = self.conversations[conversation_id]
                agent_id = processor.virtual_agent_id
                cleanup_on_stream_end = (
                    not processor.can_be_deleted
                    and stream_end_reason != "client_half_close"
                    and self.router.should_cleanup_on_client_stream_end(agent_id)
                    is True
                )
                if processor.can_be_deleted or cleanup_on_stream_end:
                    termination_reason = (
                        "completed" if processor.can_be_deleted else stream_end_reason
                    )
                    self.logger.debug(
                        "Cleaning up conversation %s (reason=%s)",
                        conversation_id,
                        termination_reason,
                    )
                    self._cleanup_conversation(
                        conversation_id, termination_reason=termination_reason
                    )
                    self.add_connection_event(
                        "end", conversation_id, agent_id, reason=termination_reason
                    )
                else:
                    self.logger.debug(
                        f"Keeping conversation {conversation_id} active for potential reconnection"
                    )
