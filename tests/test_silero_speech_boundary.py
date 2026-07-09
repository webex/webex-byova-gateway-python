import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.utils.audio_normalizer import NormalizedAudioFrame
from src.utils.silero_speech_boundary import SileroSpeechBoundaryObserver


FRAME = NormalizedAudioFrame((0.0,) * 256, 8000)


class SequenceScorer:
    def __init__(self, scores):
        self.scores = iter(scores)

    def __call__(self, samples, sample_rate_hertz):
        return next(self.scores)


def test_speech_started_once_after_debounce():
    observer = SileroSpeechBoundaryObserver(
        "conv", scorer=SequenceScorer([0.9, 0.9, 0.9]), start_debounce_ms=96
    )

    signals = [signal for _ in range(3) for signal in observer.observe(FRAME)]

    assert [signal.kind for signal in signals] == ["speech_started"]


def test_speech_ended_once_after_configured_silence():
    observer = SileroSpeechBoundaryObserver(
        "conv", scorer=SequenceScorer([0.9, 0.9, 0.9] + [0.1] * 4),
        start_debounce_ms=96,
        end_silence_ms=128,
    )

    signals = [signal for _ in range(7) for signal in observer.observe(FRAME)]

    assert [signal.kind for signal in signals] == ["speech_started", "speech_ended"]


def test_default_end_silence_is_one_second():
    observer = SileroSpeechBoundaryObserver("conv", scorer=SequenceScorer([]))

    assert observer.end_silence_ms == 1000


def test_silero_model_loads_once_per_observer(monkeypatch):
    model = MagicMock(return_value=SimpleNamespace(item=lambda: 0.9))
    load_model = MagicMock(return_value=model)
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(float32=object(), tensor=lambda samples, dtype: samples),
    )
    monkeypatch.setitem(
        sys.modules, "silero_vad", SimpleNamespace(load_silero_vad=load_model)
    )
    observer = SileroSpeechBoundaryObserver("conv")

    for _ in range(3):
        observer.observe(FRAME)

    load_model.assert_called_once_with()
    assert model.call_count == 3
