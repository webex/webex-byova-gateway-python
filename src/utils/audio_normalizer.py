"""Normalize declared WxCC audio encodings for speech-boundary observation."""

from dataclasses import dataclass
import struct
from typing import Tuple

from src.generated.voicevirtualagent_pb2 import VoiceInput


class UnsupportedAudioFormatError(ValueError):
    """Raised when WxCC declares an audio format Silero cannot observe."""


@dataclass(frozen=True)
class NormalizedAudioFrame:
    samples: Tuple[float, ...]
    sample_rate_hertz: int


def normalize_wxcc_audio(
    audio_data: bytes,
    encoding: int,
    sample_rate_hertz: int,
    *,
    fallback_sample_rate_hertz: int = 8000,
    fallback_encoding: int = VoiceInput.VoiceEncoding.MULAW_FORMAT,
) -> NormalizedAudioFrame:
    """Decode a declared WxCC codec to normalized mono PCM samples.

    WxCC audio frames occasionally omit mandatory metadata as protobuf's default
    value of zero. In that case, use the standard WxCC 8 kHz µ-law compatibility
    defaults; nonzero codec declarations remain authoritative.
    """
    effective_sample_rate_hertz = (
        fallback_sample_rate_hertz if sample_rate_hertz == 0 else sample_rate_hertz
    )
    if effective_sample_rate_hertz not in (8000, 16000):
        raise UnsupportedAudioFormatError(
            f"Unsupported sample rate for Silero VAD: {effective_sample_rate_hertz}"
        )
    effective_encoding = (
        fallback_encoding
        if encoding == VoiceInput.VoiceEncoding.UNSPECIFIED_FORMAT
        else encoding
    )
    if effective_encoding == VoiceInput.VoiceEncoding.LINEAR16_FORMAT:
        if len(audio_data) % 2:
            raise UnsupportedAudioFormatError("LINEAR16 audio must contain whole samples")
        samples = struct.unpack(f"<{len(audio_data) // 2}h", audio_data)
    elif effective_encoding == VoiceInput.VoiceEncoding.MULAW_FORMAT:
        samples = tuple(_mulaw_to_linear16(value) for value in audio_data)
    else:
        raise UnsupportedAudioFormatError(
            f"Unsupported WxCC audio encoding: {effective_encoding}"
        )
    return NormalizedAudioFrame(
        tuple(sample / 32768.0 for sample in samples), effective_sample_rate_hertz
    )


def _mulaw_to_linear16(value: int) -> int:
    value = ~value & 0xFF
    sample = ((value & 0x0F) << 3) + 0x84
    sample <<= (value & 0x70) >> 4
    return (0x84 - sample) if value & 0x80 else (sample - 0x84)
