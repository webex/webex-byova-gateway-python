"""Silero-backed streaming speech-boundary observation."""

from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence

from .audio_normalizer import NormalizedAudioFrame


@dataclass(frozen=True)
class SpeechBoundarySignal:
    kind: str
    conversation_id: str
    sample_rate_hertz: int


class SileroSpeechBoundaryObserver:
    """Observe normalized frames without owning connector utterance bytes."""

    def __init__(
        self, conversation_id: str, *, threshold: float = 0.5,
        start_debounce_ms: int = 96, end_silence_ms: int = 1000,
        scorer: Optional[Callable[[Sequence[float], int], float]] = None,
    ):
        self.conversation_id = conversation_id
        self.threshold = threshold
        self.start_debounce_ms = start_debounce_ms
        self.end_silence_ms = end_silence_ms
        self.scorer = scorer or self._silero_score
        self._model: Optional[Any] = None
        self._residual: List[float] = []
        self._active = False
        self._speech_ms = 0
        self._silence_ms = 0

    def observe(self, frame: NormalizedAudioFrame) -> List[SpeechBoundarySignal]:
        window_size = 256 if frame.sample_rate_hertz == 8000 else 512
        window_ms = int(window_size * 1000 / frame.sample_rate_hertz)
        self._residual.extend(frame.samples)
        signals = []
        while len(self._residual) >= window_size:
            window = self._residual[:window_size]
            del self._residual[:window_size]
            is_speech = self.scorer(window, frame.sample_rate_hertz) >= self.threshold
            if not self._active:
                self._speech_ms = self._speech_ms + window_ms if is_speech else 0
                if self._speech_ms >= self.start_debounce_ms:
                    self._active = True
                    self._silence_ms = 0
                    signals.append(SpeechBoundarySignal("speech_started", self.conversation_id, frame.sample_rate_hertz))
            elif is_speech:
                self._silence_ms = 0
            else:
                self._silence_ms += window_ms
                if self._silence_ms >= self.end_silence_ms:
                    self._active = False
                    self._speech_ms = 0
                    self._silence_ms = 0
                    signals.append(SpeechBoundarySignal("speech_ended", self.conversation_id, frame.sample_rate_hertz))
        return signals

    def _silero_score(
        self, samples: Sequence[float], sample_rate_hertz: int
    ) -> float:
        try:
            import torch
            from silero_vad import load_silero_vad
        except ImportError as error:
            raise RuntimeError("Silero VAD dependencies are required") from error
        if self._model is None:
            self._model = load_silero_vad()
        return float(
            self._model(
                torch.tensor(samples, dtype=torch.float32), sample_rate_hertz
            ).item()
        )
