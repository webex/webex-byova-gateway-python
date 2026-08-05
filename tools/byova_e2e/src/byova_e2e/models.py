"""Shared data models for BYOVA E2E caller runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ExpectedOutcome(str, Enum):
    """Caller-observable outcome required for a successful E2E run."""

    RESPONSE = "response"
    RESPONSE_START = "response-start"
    SESSION_END = "session-end"
    TRANSFER = "transfer"


@dataclass(frozen=True)
class AudioAsset:
    """One prepared caller-audio file available to the browser."""

    path: Path
    sha256: str
    duration_seconds: float


@dataclass(frozen=True)
class RunAction:
    """Inject one prepared caller-audio asset."""

    audio_index: int
    name: str | None = None


@dataclass(frozen=True)
class RunExpectation:
    """Wait for one caller-observable outcome."""

    outcome: ExpectedOutcome
    response_prompts: int = 1
    connected_observation_seconds: float = 0.0
    max_latency_seconds: float | None = None
    name: str | None = None


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
    remote_prompt_occurrence: int = 1
    require_remote_response: bool = False
    response_timeout_seconds: float = 30.0
    expected_outcome: ExpectedOutcome | None = None
    expected_response_prompts: int = 1
    connected_observation_seconds: float = 0.0
    headless: bool = False
    audio_assets: tuple[AudioAsset, ...] = ()
    steps: tuple[RunAction | RunExpectation, ...] = ()

    def prepared_audio(self) -> tuple[AudioAsset, ...]:
        """Return multi-step assets or the legacy single caller fixture."""
        if self.audio_assets:
            return self.audio_assets
        return (
            AudioAsset(
                path=self.audio_path,
                sha256=self.audio_sha256,
                duration_seconds=self.audio_duration_seconds,
            ),
        )


@dataclass(frozen=True)
class RunEvent:
    """An event emitted by the browser media client."""

    name: str
    timestamp: float
    details: dict[str, Any] = field(default_factory=dict)
    received_at_utc: str | None = None
