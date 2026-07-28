"""Named live-call scenarios for the current GECX regression contract."""

from __future__ import annotations

from dataclasses import dataclass

from .models import ExpectedOutcome


@dataclass(frozen=True)
class Scenario:
    """One repeatable caller fixture and its caller-observable assertion."""

    name: str
    description: str
    text: str | None = None
    text_segments: tuple[str, ...] = ()
    segment_pause_ms: int = 1000
    expected_outcome: ExpectedOutcome = ExpectedOutcome.RESPONSE
    expected_response_prompts: int = 1


SCENARIOS: dict[str, Scenario] = {
    "normal-response": Scenario(
        name="normal-response",
        description="A short request receives a complete virtual-agent response.",
        text="I need a hotel.",
    ),
    "natural-pause": Scenario(
        name="natural-pause",
        description=(
            "Two speech segments separated by a bounded pause remain one caller turn."
        ),
        text_segments=("I'd like to book", "a room in San Jose"),
        segment_pause_ms=1800,
    ),
    "task-complete": Scenario(
        name="task-complete",
        description=(
            "The virtual agent closes a completed interaction and WxCC disconnects "
            "the caller."
        ),
        text="Thank you, goodbye.",
        expected_outcome=ExpectedOutcome.SESSION_END,
    ),
    "transfer": Scenario(
        name="transfer",
        description=("The caller hears the CES and WxCC transfer announcement epochs."),
        text="Please transfer me to a human agent.",
        expected_outcome=ExpectedOutcome.TRANSFER,
        expected_response_prompts=2,
    ),
}


def get_scenario(name: str) -> Scenario:
    """Return one known scenario."""
    return SCENARIOS[name]
