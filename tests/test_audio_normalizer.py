import struct

import pytest

from src.generated.voicevirtualagent_pb2 import VoiceInput
from src.utils.audio_normalizer import UnsupportedAudioFormatError, normalize_wxcc_audio


def test_normalize_linear16_uses_declared_little_endian_codec():
    frame = normalize_wxcc_audio(
        struct.pack("<3h", -32768, 0, 32767),
        VoiceInput.VoiceEncoding.LINEAR16_FORMAT,
        8000,
    )

    assert frame.sample_rate_hertz == 8000
    assert frame.samples == pytest.approx((-1.0, 0.0, 32767 / 32768))


def test_normalize_uses_default_rate_when_wxcc_omits_sample_rate():
    frame = normalize_wxcc_audio(
        struct.pack("<2h", -32768, 32767),
        VoiceInput.VoiceEncoding.LINEAR16_FORMAT,
        0,
    )

    assert frame.sample_rate_hertz == 8000


def test_normalize_uses_standard_mulaw_when_wxcc_omits_encoding():
    frame = normalize_wxcc_audio(
        bytes((0xFF, 0x00)),
        VoiceInput.VoiceEncoding.UNSPECIFIED_FORMAT,
        8000,
    )

    assert frame.samples[0] == pytest.approx(0.0, abs=0.01)
    assert frame.samples[1] < 0.0


def test_normalize_uses_configured_fallback_when_wxcc_omits_sample_rate():
    frame = normalize_wxcc_audio(
        struct.pack("<2h", -32768, 32767),
        VoiceInput.VoiceEncoding.LINEAR16_FORMAT,
        0,
        fallback_sample_rate_hertz=16000,
    )

    assert frame.sample_rate_hertz == 16000


def test_normalize_mulaw_uses_declared_codec():
    frame = normalize_wxcc_audio(
        bytes((0xFF, 0x00)), VoiceInput.VoiceEncoding.MULAW_FORMAT, 8000
    )

    assert frame.sample_rate_hertz == 8000
    assert frame.samples[0] == pytest.approx(0.0, abs=0.01)
    assert frame.samples[1] < 0.0


def test_normalizer_rejects_unsupported_declared_format():
    with pytest.raises(UnsupportedAudioFormatError, match="encoding"):
        normalize_wxcc_audio(b"audio", VoiceInput.VoiceEncoding.ALAW_FORMAT, 8000)
