"""Translate WebSocket JSON messages to and from the shared gRPC data model."""

from __future__ import annotations

import base64
import struct
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable

from google.protobuf.json_format import MessageToDict
from google.protobuf.timestamp_pb2 import Timestamp

from src.generated.byova_common_pb2 import DTMFDigits, EventInput, OutputEvent
from src.generated.voicevirtualagent_pb2 import (
    VoiceInput,
    VoiceVARequest,
    VoiceVAResponse,
)

from .websocket_models import VoiceVARequestEnvelope


class UnsupportedMediaError(ValueError):
    """Raised when a response cannot be framed without transcoding."""


def request_to_protobuf(envelope: VoiceVARequestEnvelope) -> VoiceVARequest:
    """Convert a validated WebSocket request into the shared request model."""

    payload = envelope.payload
    request = VoiceVARequest(
        conversation_id=payload.conversation_id,
        customer_org_id=payload.customer_org_id,
        virtual_agent_id=payload.virtual_agent_id or "",
        allow_partial_responses=payload.allow_partial_responses,
        vendor_specific_config=payload.vendor_specific_config or "",
        additional_info=payload.additional_info,
    )
    input_value = payload.voice_va_input_type
    if hasattr(input_value, "audio_input"):
        audio = input_value.audio_input
        timestamp = Timestamp()
        if audio.audio_timestamp is not None:
            timestamp.FromDatetime(audio.audio_timestamp)
        request.audio_input.CopyFrom(
            VoiceInput(
                caller_audio=(
                    base64.b64decode(audio.caller_audio_b64, validate=True)
                    if audio.caller_audio_b64 is not None
                    else b""
                ),
                encoding=VoiceInput.VoiceEncoding.Value(audio.encoding),
                sample_rate_hertz=audio.sample_rate_hertz,
                audio_timestamp=timestamp,
                language_code=audio.language_code or "",
                is_single_utterance=audio.is_single_utterance,
            )
        )
    elif hasattr(input_value, "dtmf_input"):
        request.dtmf_input.dtmf_events.extend(
            DTMFDigits.Value(value) for value in input_value.dtmf_input.dtmf_events
        )
    else:
        event = input_value.event_input
        request.event_input.event_type = EventInput.EventType.Value(event.event_type)
        request.event_input.name = event.name or ""
        request.event_input.parameters.update(event.parameters)
    return request


def is_session_start(envelope: VoiceVARequestEnvelope) -> bool:
    value = envelope.payload.voice_va_input_type
    return (
        hasattr(value, "event_input")
        and value.event_input.event_type == "SESSION_START"
    )


def _text_content(value: Any) -> dict[str, Any] | None:
    field = value.WhichOneof("input_content")
    if not field:
        return None
    result: dict[str, Any] = {field: getattr(value, field)}
    if value.language_code:
        result["language_code"] = value.language_code
    return result


def response_to_payload(
    response: VoiceVAResponse, *, include_audio: bool = True
) -> dict[str, Any]:
    """Convert a shared response into the intended WebSocket JSON payload."""

    payload: dict[str, Any] = {
        "response_type": VoiceVAResponse.ResponseType.Name(response.response_type)
    }
    if response.prompts:
        prompts = []
        for prompt in response.prompts:
            value: dict[str, Any] = {"is_barge_in_enabled": prompt.is_barge_in_enabled}
            if prompt.text:
                value["text"] = prompt.text
            if prompt.audio_uri:
                value["audio_uri"] = prompt.audio_uri
            if include_audio and prompt.audio_content:
                value["audio_content_b64"] = base64.b64encode(
                    prompt.audio_content
                ).decode("ascii")
            prompts.append(value)
        payload["prompts"] = prompts
    if response.output_events:
        payload["output_events"] = [
            {
                "event_type": OutputEvent.EventType.Name(event.event_type),
                **({"name": event.name} if event.name else {}),
                **(
                    {
                        "metadata": MessageToDict(
                            event.metadata, preserving_proto_field_name=True
                        )
                    }
                    if event.metadata
                    else {}
                ),
            }
            for event in response.output_events
        ]
    if response.input_sensitive:
        payload["input_sensitive"] = True
    if response.input_mode:
        payload["input_mode"] = (
            response.DESCRIPTOR.fields_by_name["input_mode"]
            .enum_type.values_by_number[response.input_mode]
            .name
        )
    if response.HasField("input_handling_config"):
        payload["input_handling_config"] = MessageToDict(
            response.input_handling_config,
            preserving_proto_field_name=True,
            use_integers_for_enums=False,
        )
        # WebSocket and gRPC have separate schemas. The WebSocket contract's
        # supported no-input timer is not present in the gRPC proto reused by
        # the conversation engine, so add it only at this wire boundary.
        if payload.get("input_mode") in {"INPUT_EVENT_DTMF", "INPUT_VOICE_DTMF"}:
            payload["input_handling_config"]["speech_timers"] = {
                "no_input_timeout_msec": 30000
            }
    transcript = _text_content(response.session_transcript)
    if transcript:
        payload["session_transcript"] = transcript
    summary = _text_content(response.session_summary)
    if summary:
        payload["session_summary"] = summary
    return payload


def _wav_frames(audio: bytes) -> bytes:
    """Return the encoded bytes in a RIFF/WAVE data chunk.

    Python's :mod:`wave` reader accepts only PCM and a narrow set of
    extensible encodings.  WxCC-compatible Local Audio files can use G.711
    mu-law (format tag 7), and raw WebSocket framing must preserve those bytes
    rather than decode them.  Parse the RIFF container directly and leave the
    media payload untouched.
    """

    if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise UnsupportedMediaError("invalid WAV response audio")

    riff_size = struct.unpack_from("<I", audio, 4)[0]
    if riff_size + 8 > len(audio):
        raise UnsupportedMediaError("invalid WAV response audio")

    offset = 12
    riff_end = min(riff_size + 8, len(audio))
    while offset + 8 <= riff_end:
        chunk_id = audio[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", audio, offset + 4)[0]
        data_start = offset + 8
        data_end = data_start + chunk_size
        if data_end > riff_end:
            raise UnsupportedMediaError("invalid WAV response audio")
        if chunk_id == b"data":
            return audio[data_start:data_end]
        offset = data_end + (chunk_size & 1)

    raise UnsupportedMediaError("invalid WAV response audio")


def _chunks(audio: bytes, chunk_size: int) -> Iterable[bytes]:
    if not audio:
        return
    if len(audio) < 100:
        raise UnsupportedMediaError("raw response audio is smaller than 100 bytes")
    offset = 0
    while offset < len(audio):
        end = min(offset + chunk_size, len(audio))
        if 0 < len(audio) - end < 100:
            # Merge a short tail only if it fits; otherwise reserve 100 bytes.
            end = len(audio) if len(audio) - offset <= 65_536 else len(audio) - 100
        yield audio[offset:end]
        offset = end


def frame_response_payloads(
    response: VoiceVAResponse,
    *,
    output_mode: str,
    chunk_size: int = 3_200,
) -> list[dict[str, Any]]:
    """Apply the connector's frozen WebSocket output framing policy."""

    if not 100 <= chunk_size <= 65_536:
        raise ValueError("chunk_size must be between 100 and 65536 bytes")
    payload = response_to_payload(response, include_audio=False)
    prompts = payload.get("prompts", [])
    audio_prompts = [
        (source.audio_content, item)
        for source, item in zip(response.prompts, prompts)
        if source.audio_content
    ]
    if any(item.get("audio_uri") for audio, item in audio_prompts):
        raise UnsupportedMediaError("a prompt cannot mix inline audio and an audio URI")
    if output_mode == "wav_final":
        if response.response_type == VoiceVAResponse.ResponseType.CHUNK:
            raise UnsupportedMediaError("wav_final connector returned CHUNK audio")
        for audio, item in audio_prompts:
            if not audio.startswith(b"RIFF"):
                raise UnsupportedMediaError("wav_final response must contain WAV audio")
            item["audio_content_b64"] = base64.b64encode(audio).decode("ascii")
        return [payload]
    if output_mode != "raw_chunk":
        raise UnsupportedMediaError(f"unsupported output mode: {output_mode}")

    if response.response_type == VoiceVAResponse.ResponseType.CHUNK:
        for audio, item in audio_prompts:
            if not 100 <= len(audio) <= 65_536:
                raise UnsupportedMediaError("CHUNK audio must be 100 to 65536 bytes")
            item["audio_content_b64"] = base64.b64encode(audio).decode("ascii")
        return [payload]
    if not audio_prompts:
        return [payload]

    framed: list[dict[str, Any]] = []
    chunk_collection_metadata = {
        key: deepcopy(payload[key])
        for key in ("input_sensitive", "input_mode", "input_handling_config")
        if key in payload
    }
    for prompt_index, (audio, item) in enumerate(audio_prompts):
        if audio.startswith(b"RIFF"):
            audio = _wav_frames(audio)
        for index, chunk in enumerate(_chunks(audio, chunk_size)):
            chunk_prompt = {
                "audio_content_b64": base64.b64encode(chunk).decode("ascii"),
                "is_barge_in_enabled": item.get("is_barge_in_enabled", False),
            }
            if index == 0 and prompt_index == 0 and item.get("text"):
                chunk_prompt["text"] = item["text"]
            chunk_payload: dict[str, Any] = {
                "prompts": [chunk_prompt],
                "response_type": "CHUNK",
            }
            # WxCC fixes the prompt's media and input-collection behavior from
            # the first response frame. Repeat the schema-valid collection
            # contract on every audio CHUNK so an intermediate frame cannot
            # replace that state with an omitted/default configuration.
            chunk_payload.update(deepcopy(chunk_collection_metadata))
            framed.append(chunk_payload)
        item["audio_content_b64"] = ""

    final_payload = deepcopy(payload)
    final_payload["response_type"] = payload["response_type"]
    final_prompts = []
    # All inline prompts above are serialized into one ordered CHUNK stream,
    # so the stream requires exactly one empty-audio FINAL terminator even
    # when a connector supplied multiple prompt objects.
    inline_audio_terminated = False
    for item in final_payload.pop("prompts", []):
        had_inline_audio = "audio_content_b64" in item
        item.pop("text", None)
        if had_inline_audio and not inline_audio_terminated:
            # The WxCC chunk contract terminates a stream with a FINAL prompt
            # whose inline audio value is present but empty.  A prompt-less
            # FINAL can leave the client in the preceding collection state,
            # so retain the explicit zero-byte stream terminator used by the
            # official WebSocket simulator.
            item["audio_content_b64"] = ""
            final_prompts.append(item)
            inline_audio_terminated = True
        elif item.get("audio_uri"):
            item.pop("audio_content_b64", None)
            final_prompts.append(item)
    if final_prompts:
        final_payload["prompts"] = final_prompts
    framed.append(final_payload)
    return framed


def envelope(
    *, message_type: str, seq: int, conversation_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    return {
        "type": message_type,
        "seq": seq,
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "conversation_id": conversation_id,
        "payload": payload,
    }
