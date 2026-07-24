"""Deterministic prompt-end gate controlled by the Python orchestrator."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromptGate:
    """Release one caller utterance after remote audio has gone quiet."""

    silence_seconds: float
    remote_activity_observed: bool = False
    remote_active: bool = False
    quiet_since: float | None = None
    injected: bool = False

    def remote_audio_active(self) -> None:
        self.remote_activity_observed = True
        self.remote_active = True
        self.quiet_since = None

    def remote_audio_inactive(self, now: float) -> None:
        if self.remote_activity_observed and self.remote_active:
            self.remote_active = False
            self.quiet_since = now

    def ready_to_inject(self, now: float) -> bool:
        return (
            not self.injected
            and self.remote_activity_observed
            and not self.remote_active
            and self.quiet_since is not None
            and now - self.quiet_since >= self.silence_seconds
        )

    def mark_injected(self) -> None:
        self.injected = True
