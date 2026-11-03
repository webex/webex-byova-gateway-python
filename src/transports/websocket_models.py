"""Strict runtime models for the Webex BYOVA WebSocket JSON contract.

The published AsyncAPI composes a closed base envelope with ``allOf`` and then
adds derived fields. Strict JSON Schema validators therefore reject the
official examples. These concrete models preserve the intended official wire
shape while still rejecting unknown fields.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

NonEmptyString = Annotated[str, StringConstraints(min_length=1, max_length=512)]
MAX_AUDIO_BYTES = 65_536


def _normalize_map_entries(value: Any) -> Any:
    """Normalize protobuf-style JSON map entries into an ordinary mapping.

    WxCC currently emits protobuf map fields as repeated ``key``/``value``
    entries, including ``[]`` for an empty map. The published WebSocket schema
    models the same fields as JSON objects, so accept either representation and
    keep the rest of the model strict.
    """

    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if not isinstance(value, list):
        return value

    normalized: dict[str, Any] = {}
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != {"key", "value"}:
            raise ValueError("map entries must contain only key and value")
        key = entry["key"]
        if not isinstance(key, str):
            raise ValueError("map entry keys must be strings")
        if key in normalized:
            raise ValueError("map entry keys must be unique")
        normalized[key] = entry["value"]
    return normalized


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VoiceInput(StrictModel):
    caller_audio_b64: str | None = None
    encoding: Literal[
        "UNSPECIFIED_FORMAT",
        "LINEAR16_FORMAT",
        "MULAW_FORMAT",
        "ALAW_FORMAT",
    ]
    sample_rate_hertz: int = Field(gt=0, le=192_000)
    audio_timestamp: datetime | None = None
    language_code: str | None = Field(default=None, max_length=64)
    is_single_utterance: bool = False

    @field_validator("is_single_utterance", mode="before")
    @classmethod
    def normalize_nullable_single_utterance(cls, value: Any) -> Any:
        return False if value is None else value

    @field_validator("caller_audio_b64")
    @classmethod
    def validate_audio(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("caller_audio_b64 must be valid base64") from error
        if len(decoded) > MAX_AUDIO_BYTES:
            raise ValueError(f"caller audio exceeds {MAX_AUDIO_BYTES} bytes")
        return value


DTMFDigit = Literal[
    "DTMF_EVENT_UNSPECIFIED",
    "DTMF_DIGIT_ONE",
    "DTMF_DIGIT_TWO",
    "DTMF_DIGIT_THREE",
    "DTMF_DIGIT_FOUR",
    "DTMF_DIGIT_FIVE",
    "DTMF_DIGIT_SIX",
    "DTMF_DIGIT_SEVEN",
    "DTMF_DIGIT_EIGHT",
    "DTMF_DIGIT_NINE",
    "DTMF_DIGIT_ZERO",
    "DTMF_DIGIT_A",
    "DTMF_DIGIT_B",
    "DTMF_DIGIT_C",
    "DTMF_DIGIT_D",
    "DTMF_DIGIT_STAR",
    "DTMF_DIGIT_POUND",
]


class DTMFInputs(StrictModel):
    dtmf_events: list[DTMFDigit] = Field(min_length=1, max_length=64)


class EventInput(StrictModel):
    event_type: Literal[
        "UNSPECIFIED_INPUT",
        "SESSION_START",
        "SESSION_END",
        "NO_INPUT",
        "START_OF_DTMF",
        "CUSTOM_EVENT",
    ]
    name: str | None = Field(default=None, max_length=256)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters", mode="before")
    @classmethod
    def normalize_parameters(cls, value: Any) -> Any:
        return _normalize_map_entries(value)


class VoiceInputWrapper(StrictModel):
    audio_input: VoiceInput


class DTMFInputWrapper(StrictModel):
    dtmf_input: DTMFInputs


class EventInputWrapper(StrictModel):
    event_input: EventInput


VoiceVAInput = Union[VoiceInputWrapper, DTMFInputWrapper, EventInputWrapper]


class VoiceVARequest(StrictModel):
    conversation_id: NonEmptyString
    customer_org_id: NonEmptyString
    virtual_agent_id: NonEmptyString | None = None
    allow_partial_responses: bool = False
    vendor_specific_config: str | None = Field(default=None, max_length=16_384)
    voice_va_input_type: VoiceVAInput
    additional_info: dict[str, str] = Field(default_factory=dict)

    @field_validator("additional_info", mode="before")
    @classmethod
    def normalize_additional_info(cls, value: Any) -> Any:
        return _normalize_map_entries(value)


class VoiceVARequestEnvelope(StrictModel):
    type: Literal["VOICE_VA_REQUEST"]
    seq: int = Field(ge=1)
    ts: datetime
    conversation_id: NonEmptyString
    metadata: dict[str, Any] = Field(default_factory=dict)
    payload: VoiceVARequest

    @field_validator("metadata", mode="before")
    @classmethod
    def normalize_metadata(cls, value: Any) -> Any:
        return _normalize_map_entries(value)

    @model_validator(mode="after")
    def identifiers_match(self) -> VoiceVARequestEnvelope:
        if self.conversation_id != self.payload.conversation_id:
            raise ValueError("envelope and payload conversation_id must match")
        return self


class PingEnvelope(StrictModel):
    type: Literal["PING"]
    seq: int = Field(ge=1)
    ts: datetime
    conversation_id: NonEmptyString
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def normalize_metadata(cls, value: Any) -> Any:
        return _normalize_map_entries(value)


class ListVARequest(BaseModel):
    # Cisco's reference handler explicitly ignores unknown discovery fields.
    # Keep required typed fields bounded while remaining forward compatible.
    model_config = ConfigDict(extra="ignore")

    customer_org_id: NonEmptyString
    is_default_virtual_agent_enabled: bool = False


IncomingEnvelope = Union[VoiceVARequestEnvelope, PingEnvelope]


def parse_incoming_envelope(value: Any) -> IncomingEnvelope:
    """Parse an inbound envelope using its discriminator."""

    if not isinstance(value, dict):
        raise ValueError("WebSocket message must be a JSON object")
    message_type = value.get("type")
    if message_type == "VOICE_VA_REQUEST":
        return VoiceVARequestEnvelope.model_validate(value)
    if message_type == "PING":
        return PingEnvelope.model_validate(value)
    raise ValueError(f"unsupported message type: {message_type!r}")
