"""Tests for WebSocket and shared-message translation."""

import base64
import io
import struct
import wave

import pytest

from src.generated.byova_common_pb2 import DTMFDigits, EventInput, OutputEvent
from src.generated.voicevirtualagent_pb2 import (
    Prompt,
    VoiceVAInputMode,
    VoiceVAResponse,
)
from src.transports.websocket_adapter import (
    UnsupportedMediaError,
    frame_response_payloads,
    request_to_protobuf,
    response_to_payload,
)
from src.transports.websocket_models import VoiceVARequestEnvelope


def _request() -> VoiceVARequestEnvelope:
    return VoiceVARequestEnvelope.model_validate(
        {
            "type": "VOICE_VA_REQUEST",
            "seq": 1,
            "ts": "2026-09-08T12:00:00Z",
            "conversation_id": "call-1",
            "payload": {
                "conversation_id": "call-1",
                "customer_org_id": "org-1",
                "virtual_agent_id": "agent-1",
                "voice_va_input_type": {"event_input": {"event_type": "SESSION_START"}},
            },
        }
    )


def _wav(audio: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(1)
        wav_file.setframerate(8000)
        wav_file.writeframes(audio)
    return output.getvalue()


def _mulaw_wav(audio: bytes) -> bytes:
    """Build a mono 8 kHz G.711 mu-law WAV without decoding the payload."""
    fmt = struct.pack("<HHIIHH", 7, 1, 8000, 8000, 1, 8)
    chunks = b"fmt " + struct.pack("<I", len(fmt)) + fmt
    chunks += b"data" + struct.pack("<I", len(audio)) + audio
    return b"RIFF" + struct.pack("<I", len(chunks) + 4) + b"WAVE" + chunks


def test_request_maps_to_existing_protobuf_contract():
    request = request_to_protobuf(_request())
    assert request.customer_org_id == "org-1"
    assert request.virtual_agent_id == "agent-1"
    assert request.event_input.event_type == EventInput.EventType.SESSION_START


def test_response_maps_audio_events_and_summary_to_json_names():
    response = VoiceVAResponse(
        prompts=[
            Prompt(
                text="Transferring",
                audio_content=b"audio",
                is_barge_in_enabled=False,
            )
        ],
        output_events=[
            OutputEvent(
                event_type=OutputEvent.EventType.TRANSFER_TO_AGENT,
                name="transfer_requested",
                metadata={"summary": "Customer needs help"},
            )
        ],
        response_type=VoiceVAResponse.ResponseType.FINAL,
    )
    response.session_summary.text = "Customer needs help"
    payload = response_to_payload(response)
    assert payload["response_type"] == "FINAL"
    assert base64.b64decode(payload["prompts"][0]["audio_content_b64"]) == b"audio"
    assert payload["output_events"][0]["event_type"] == "TRANSFER_TO_AGENT"
    assert payload["session_summary"]["text"] == "Customer needs help"


def test_raw_chunk_mode_strips_wav_and_adds_empty_final():
    audio = bytes(range(256)) * 30
    response = VoiceVAResponse(
        prompts=[
            Prompt(
                text="Hello",
                audio_content=_wav(audio),
                is_barge_in_enabled=True,
            )
        ],
        response_type=VoiceVAResponse.ResponseType.FINAL,
    )
    payloads = frame_response_payloads(
        response, output_mode="raw_chunk", chunk_size=3200
    )
    assert [value["response_type"] for value in payloads] == [
        "CHUNK",
        "CHUNK",
        "CHUNK",
        "FINAL",
    ]
    rebuilt = b"".join(
        base64.b64decode(value["prompts"][0]["audio_content_b64"])
        for value in payloads[:-1]
    )
    assert rebuilt == audio
    assert payloads[-1]["prompts"] == [
        {"audio_content_b64": "", "is_barge_in_enabled": True}
    ]


def test_raw_chunk_mode_configures_dtmf_on_first_frame():
    response = VoiceVAResponse(
        prompts=[Prompt(audio_content=_wav(bytes(range(256)) * 30))],
        response_type=VoiceVAResponse.ResponseType.FINAL,
        input_mode=VoiceVAInputMode.INPUT_VOICE_DTMF,
    )
    response.input_handling_config.dtmf_config.dtmf_input_length = 9
    response.input_handling_config.dtmf_config.inter_digit_timeout_msec = 5000
    response.input_handling_config.dtmf_config.termchar = DTMFDigits.DTMF_DIGIT_POUND

    payloads = frame_response_payloads(
        response, output_mode="raw_chunk", chunk_size=3200
    )

    assert payloads[0]["response_type"] == "CHUNK"
    assert payloads[0]["input_mode"] == "INPUT_VOICE_DTMF"
    assert payloads[0]["input_handling_config"]["dtmf_config"] == {
        "inter_digit_timeout_msec": 5000,
        "termchar": "DTMF_DIGIT_POUND",
        "dtmf_input_length": 9,
    }
    assert payloads[0]["input_handling_config"]["speech_timers"] == {
        "no_input_timeout_msec": 30000
    }
    assert payloads[1]["input_mode"] == "INPUT_VOICE_DTMF"
    assert payloads[1]["input_handling_config"] == payloads[0]["input_handling_config"]


def test_raw_chunk_mode_preserves_mulaw_wav_payload():
    audio = bytes(range(256)) * 30
    response = VoiceVAResponse(
        prompts=[Prompt(audio_content=_mulaw_wav(audio))],
        response_type=VoiceVAResponse.ResponseType.FINAL,
    )

    payloads = frame_response_payloads(
        response, output_mode="raw_chunk", chunk_size=3200
    )

    rebuilt = b"".join(
        base64.b64decode(value["prompts"][0]["audio_content_b64"])
        for value in payloads[:-1]
    )
    assert rebuilt == audio
    assert payloads[-1]["response_type"] == "FINAL"


@pytest.mark.parametrize(
    "audio",
    [
        b"RIFF\x10\x00\x00\x00WAVEdata\x08\x00\x00\x00short",
        b"RIFF\x04\x00\x00\x00WAVE",
    ],
)
def test_raw_chunk_mode_rejects_malformed_wav_chunks(audio):
    response = VoiceVAResponse(
        prompts=[Prompt(audio_content=audio)],
        response_type=VoiceVAResponse.ResponseType.FINAL,
    )

    with pytest.raises(UnsupportedMediaError, match="invalid WAV"):
        frame_response_payloads(response, output_mode="raw_chunk")


def test_raw_chunk_mode_uses_one_terminator_for_multiple_inline_prompts():
    response = VoiceVAResponse(
        prompts=[
            Prompt(audio_content=b"a" * 100),
            Prompt(audio_content=b"b" * 100),
        ],
        response_type=VoiceVAResponse.ResponseType.FINAL,
    )

    payloads = frame_response_payloads(
        response, output_mode="raw_chunk", chunk_size=100
    )

    assert [
        base64.b64decode(value["prompts"][0]["audio_content_b64"])
        for value in payloads[:-1]
    ] == [b"a" * 100, b"b" * 100]
    assert payloads[-1]["prompts"] == [
        {"audio_content_b64": "", "is_barge_in_enabled": False}
    ]


def test_raw_chunk_mode_rejects_mixed_inline_and_uri_audio():
    response = VoiceVAResponse(
        prompts=[Prompt(audio_content=b"a" * 100, audio_uri="https://example.test/a")],
        response_type=VoiceVAResponse.ResponseType.FINAL,
    )

    with pytest.raises(UnsupportedMediaError, match="cannot mix"):
        frame_response_payloads(response, output_mode="raw_chunk")


def test_wav_final_rejects_raw_audio_and_chunk_responses():
    raw_final = VoiceVAResponse(
        prompts=[Prompt(audio_content=b"raw audio" * 20)],
        response_type=VoiceVAResponse.ResponseType.FINAL,
    )
    with pytest.raises(UnsupportedMediaError, match="WAV"):
        frame_response_payloads(raw_final, output_mode="wav_final")

    chunk = VoiceVAResponse(
        prompts=[Prompt(audio_content=b"x" * 100)],
        response_type=VoiceVAResponse.ResponseType.CHUNK,
    )
    with pytest.raises(UnsupportedMediaError, match="CHUNK"):
        frame_response_payloads(chunk, output_mode="wav_final")


@pytest.mark.parametrize("chunk_size", [100, 3200, 65_536])
@pytest.mark.parametrize("tail_size", [1, 99, 100])
def test_raw_chunk_boundaries_preserve_audio_and_wire_limits(chunk_size, tail_size):
    audio = bytes(range(256)) * (chunk_size // 256 + 1)
    audio = audio[:chunk_size] + b"x" * tail_size
    response = VoiceVAResponse(
        prompts=[Prompt(audio_content=audio)], response_type=VoiceVAResponse.FINAL
    )
    payloads = frame_response_payloads(
        response, output_mode="raw_chunk", chunk_size=chunk_size
    )
    chunks = [
        base64.b64decode(item["prompts"][0]["audio_content_b64"])
        for item in payloads[:-1]
    ]
    assert all(100 <= len(chunk) <= 65_536 for chunk in chunks)
    assert b"".join(chunks) == audio
    assert payloads[-1]["response_type"] == "FINAL"
    assert payloads[-1]["prompts"][0]["audio_content_b64"] == ""
