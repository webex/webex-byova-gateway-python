"""Deterministic prompt-end gate controlled by the Python orchestrator."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromptGate:
    """Release one caller utterance after remote audio has gone quiet."""

    silence_seconds: float
    target_prompt_occurrence: int = 1
    remote_activity_observed: bool = False
    remote_active: bool = False
    quiet_since: float | None = None
    completed_prompt_count: int = 0
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
        completed = (
            not self.injected
            and self.remote_activity_observed
            and not self.remote_active
            and self.quiet_since is not None
            and now - self.quiet_since >= self.silence_seconds
        )
        if not completed:
            return False
        self.completed_prompt_count += 1
        self.quiet_since = None
        return self.completed_prompt_count >= self.target_prompt_occurrence

    def mark_injected(self) -> None:
        self.injected = True
