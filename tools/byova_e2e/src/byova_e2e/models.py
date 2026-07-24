"""Shared data models for BYOVA E2E caller runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunConfig:
    """Validated inputs used by a single browser calling run."""

    destination: str
    access_token: str
    audio_path: Path
    audio_sha256: str
    audio_duration_seconds: float
    remote_silence_seconds: float
    initial_silence_fallback_seconds: float
    prompt_timeout_seconds: float
    call_timeout_seconds: float
    post_audio_grace_seconds: float
    headless: bool = False


@dataclass(frozen=True)
class RunEvent:
    """An event emitted by the browser media client."""

    name: str
    timestamp: float
    details: dict[str, Any] = field(default_factory=dict)
