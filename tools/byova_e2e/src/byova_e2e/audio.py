"""Local macOS TTS rendering and deterministic WAV preparation."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf


TARGET_SAMPLE_RATE = 16_000


class AudioPreparationError(RuntimeError):
    """Raised when a caller input cannot be rendered into a usable WAV."""


@dataclass(frozen=True)
class PreparedAudio:
    """The normalised local-audio asset that the browser will inject."""

    path: Path
    sha256: str
    duration_seconds: float


def _write_mono_pcm(source: Path, destination: Path) -> PreparedAudio:
    try:
        samples, sample_rate = sf.read(source, dtype="float32", always_2d=True)
    except Exception as error:  # soundfile exposes backend-specific errors
        raise AudioPreparationError(f"Cannot read WAV input {source}: {error}") from error

    if sample_rate <= 0 or samples.size == 0:
        raise AudioPreparationError(f"WAV input {source} contains no audio")

    mono = samples.mean(axis=1)
    if sample_rate != TARGET_SAMPLE_RATE:
        source_positions = np.arange(len(mono), dtype=np.float64) / sample_rate
        target_length = round(len(mono) * TARGET_SAMPLE_RATE / sample_rate)
        target_positions = np.arange(target_length, dtype=np.float64) / TARGET_SAMPLE_RATE
        mono = np.interp(target_positions, source_positions, mono).astype(np.float32)

    sf.write(destination, mono, TARGET_SAMPLE_RATE, subtype="PCM_16")
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    return PreparedAudio(
        path=destination,
        sha256=digest,
        duration_seconds=len(mono) / TARGET_SAMPLE_RATE,
    )


def prepare_wav(source: Path, destination: Path) -> PreparedAudio:
    """Convert a caller-supplied WAV into one mono, 16 kHz PCM asset."""
    if not source.is_file():
        raise AudioPreparationError(f"WAV input does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    return _write_mono_pcm(source, destination)


def render_text(text: str, voice: str, destination: Path) -> PreparedAudio:
    """Render text with macOS `say` and normalise it for WebRTC playback."""
    if not text.strip():
        raise AudioPreparationError("Text input must not be empty")

    raw_path = destination.with_suffix(".say.aiff")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            ["say", "-v", voice, "-o", str(raw_path), text], text=True, capture_output=True
        )
    except FileNotFoundError as error:
        raise AudioPreparationError(
            "macOS `say` is unavailable. Use --wav or run this POC on macOS."
        ) from error
    if result.returncode or not raw_path.is_file() or raw_path.stat().st_size == 0:
        raw_path.unlink(missing_ok=True)
        detail = result.stderr.strip() or f"say exited with status {result.returncode}"
        raise AudioPreparationError(f"macOS `say` could not render the requested voice: {detail}")
    return _write_mono_pcm(raw_path, destination)
