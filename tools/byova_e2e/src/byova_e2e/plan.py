"""Load Playwright-shaped, data-driven live-call test plans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from .models import ExpectedOutcome

SUPPORTED_VERSION = 1

USE_FIELDS = {
    "voice",
    "headless",
    "remoteSilenceMs",
    "remotePromptOccurrence",
    "initialSilenceFallbackSeconds",
    "promptTimeoutSeconds",
    "callTimeoutSeconds",
    "postAudioGraceSeconds",
    "responseTimeoutSeconds",
}


class TestPlanError(ValueError):
    """A user-facing test-plan configuration failure."""


@dataclass(frozen=True)
class InputStepDefinition:
    """One prepared caller-audio action in an ordered test."""

    name: str | None = None
    text: str | None = None
    text_segments: tuple[str, ...] = ()
    wav: Path | None = None
    segment_pause_ms: int | None = None


@dataclass(frozen=True)
class ExpectStepDefinition:
    """One caller-observable expectation in an ordered test."""

    outcome: ExpectedOutcome
    name: str | None = None
    response_prompts: int = 1
    connected_observation_seconds: float = 0.0
    max_latency_seconds: float | None = None


@dataclass(frozen=True)
class TestDefinition:
    """One selected test after top-level and test-level settings are merged."""

    test_id: str
    title: str
    description: str
    source_file: Path
    config_sha256: str
    steps: tuple[InputStepDefinition | ExpectStepDefinition, ...] = ()
    text: str | None = None
    text_segments: tuple[str, ...] = ()
    wav: Path | None = None
    voice: str | None = None
    segment_pause_ms: int | None = None
    headless: bool | None = None
    remote_silence_ms: int | None = None
    remote_prompt_occurrence: int | None = None
    initial_silence_fallback_seconds: float | None = None
    prompt_timeout_seconds: float | None = None
    call_timeout_seconds: float | None = None
    post_audio_grace_seconds: float | None = None
    response_timeout_seconds: float | None = None
    expected_outcome: ExpectedOutcome = ExpectedOutcome.RESPONSE
    expected_response_prompts: int = 1
    connected_observation_seconds: float = 0.0


@dataclass(frozen=True)
class TestPlan:
    """One validated test plan and its reproducibility metadata."""

    source_file: Path
    config_sha256: str
    tests: tuple[TestDefinition, ...]

    def get_test(self, test_id: str) -> TestDefinition:
        """Return one named test from this plan."""
        for selected_test in self.tests:
            if selected_test.test_id == test_id:
                return selected_test
        available = ", ".join(sorted(test.test_id for test in self.tests))
        raise TestPlanError(
            f"Unknown test {test_id!r} in {self.source_file}. Available: {available}"
        )


def load_plan(config_file: Path) -> TestPlan:
    """Load and validate every test in a versioned JSON plan."""
    path = config_file.expanduser().resolve()
    try:
        payload = path.read_bytes()
    except FileNotFoundError as error:
        raise TestPlanError(f"Test config does not exist: {path}") from error
    except OSError as error:
        raise TestPlanError(f"Unable to read test config {path}: {error}") from error
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as error:
        raise TestPlanError(
            f"Invalid JSON in test config {path} at line {error.lineno}, "
            f"column {error.colno}: {error.msg}"
        ) from error

    root = _object(raw, "test config")
    _reject_unknown(root, {"$schema", "version", "use", "tests"}, "test config")
    version = root.get("version")
    if not _is_integer(version) or version != SUPPORTED_VERSION:
        raise TestPlanError(f"test config.version must be {SUPPORTED_VERSION}")

    shared_use = _parse_use(root.get("use", {}), "test config.use")
    tests = root.get("tests")
    if not isinstance(tests, list) or not tests:
        raise TestPlanError("test config.tests must be a non-empty array")

    config_sha256 = sha256(payload).hexdigest()
    parsed_tests: list[TestDefinition] = []
    test_ids: set[str] = set()
    for index, test in enumerate(tests):
        parsed = _parse_test(test, index, path, config_sha256, shared_use)
        if parsed.test_id in test_ids:
            raise TestPlanError(f"Duplicate test id: {parsed.test_id!r}")
        test_ids.add(parsed.test_id)
        parsed_tests.append(parsed)

    return TestPlan(
        source_file=path,
        config_sha256=config_sha256,
        tests=tuple(parsed_tests),
    )


def load_test(test_id: str, config_file: Path) -> TestDefinition:
    """Load one named test from a versioned JSON test plan."""
    return load_plan(config_file).get_test(test_id)


def _parse_test(
    raw: Any,
    index: int,
    source_file: Path,
    config_sha256: str,
    shared_use: dict[str, Any],
) -> TestDefinition:
    location = f"tests[{index}]"
    value = _object(raw, location)
    _reject_unknown(value, {"id", "title", "description", "use", "steps"}, location)
    test_id = _nonempty_string(value.get("id"), f"{location}.id")
    title = _nonempty_string(value.get("title"), f"{location}.title")
    description = _optional_nonempty_string(
        value.get("description"), f"{location}.description"
    )
    test_use = _parse_use(value.get("use", {}), f"{location}.use")
    merged_use = {**shared_use, **test_use}

    raw_steps = value.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) < 2:
        raise TestPlanError(
            f"{location}.steps must contain at least one audio action and expectation"
        )
    if len(raw_steps) % 2:
        raise TestPlanError(
            f"{location}.steps must alternate audio actions and expectations"
        )

    parsed_steps: list[InputStepDefinition | ExpectStepDefinition] = []
    for step_index, raw_step in enumerate(raw_steps):
        step_location = f"{location}.steps[{step_index}]"
        if step_index % 2 == 0:
            parsed_steps.append(
                _parse_input_step(raw_step, step_location, source_file)
            )
        else:
            parsed_steps.append(_parse_expect_step(raw_step, step_location))

    for step_index, step in enumerate(parsed_steps[:-1]):
        if isinstance(step, ExpectStepDefinition) and step.outcome in {
            ExpectedOutcome.SESSION_END,
            ExpectedOutcome.TRANSFER,
        }:
            raise TestPlanError(
                f"{location}.steps[{step_index}] terminal outcome must be final"
            )
    final_expectation = parsed_steps[-1]
    if not isinstance(final_expectation, ExpectStepDefinition):
        raise AssertionError("validated test must end with an expectation")
    if final_expectation.outcome == ExpectedOutcome.RESPONSE_START:
        raise TestPlanError(
            f"{location}.steps must not end with a response-start expectation"
        )
    first_input = parsed_steps[0]
    if not isinstance(first_input, InputStepDefinition):
        raise AssertionError("validated test must start with an input action")

    return TestDefinition(
        test_id=test_id,
        title=title,
        description=description or title,
        source_file=source_file,
        config_sha256=config_sha256,
        steps=tuple(parsed_steps),
        text=first_input.text,
        text_segments=first_input.text_segments,
        wav=first_input.wav,
        segment_pause_ms=first_input.segment_pause_ms,
        voice=merged_use.get("voice"),
        headless=merged_use.get("headless"),
        remote_silence_ms=merged_use.get("remoteSilenceMs"),
        remote_prompt_occurrence=merged_use.get("remotePromptOccurrence"),
        initial_silence_fallback_seconds=merged_use.get(
            "initialSilenceFallbackSeconds"
        ),
        prompt_timeout_seconds=merged_use.get("promptTimeoutSeconds"),
        call_timeout_seconds=merged_use.get("callTimeoutSeconds"),
        post_audio_grace_seconds=merged_use.get("postAudioGraceSeconds"),
        response_timeout_seconds=merged_use.get("responseTimeoutSeconds"),
        expected_outcome=final_expectation.outcome,
        expected_response_prompts=final_expectation.response_prompts,
        connected_observation_seconds=(
            final_expectation.connected_observation_seconds
        ),
    )


def _parse_input_step(
    raw: Any, location: str, source_file: Path
) -> InputStepDefinition:
    step = _object(raw, location)
    _reject_unknown(
        step,
        {"name", "action", "text", "segments", "pauseMs", "path"},
        location,
    )
    name = _optional_nonempty_string(step.get("name"), f"{location}.name")
    action = _nonempty_string(step.get("action"), f"{location}.action")
    if action == "speak":
        has_text = "text" in step
        has_segments = "segments" in step
        if has_text == has_segments:
            raise TestPlanError(
                f"{location} with action 'speak' must define exactly one of "
                "text or segments"
            )
        if "path" in step:
            raise TestPlanError(f"{location}.path is only valid with action 'play'")
        if has_text:
            if "pauseMs" in step:
                raise TestPlanError(
                    f"{location}.pauseMs is only valid with segmented speech"
                )
            return InputStepDefinition(
                name=name,
                text=_nonempty_string(step["text"], f"{location}.text"),
            )
        segments = step["segments"]
        if not isinstance(segments, list) or len(segments) < 2:
            raise TestPlanError(
                f"{location}.segments must contain at least two strings"
            )
        return InputStepDefinition(
            name=name,
            text_segments=tuple(
                _nonempty_string(segment, f"{location}.segments[{index}]")
                for index, segment in enumerate(segments)
            ),
            segment_pause_ms=_positive_integer(
                step.get("pauseMs"), f"{location}.pauseMs"
            ),
        )
    if action == "play":
        if any(field in step for field in ("text", "segments", "pauseMs")):
            raise TestPlanError(
                f"{location} with action 'play' only accepts name, action, and path"
            )
        wav_value = _nonempty_string(step.get("path"), f"{location}.path")
        wav = Path(wav_value).expanduser()
        if not wav.is_absolute():
            wav = source_file.parent / wav
        return InputStepDefinition(name=name, wav=wav.resolve())
    raise TestPlanError(f"{location}.action must be 'speak' or 'play'")


def _parse_expect_step(raw: Any, location: str) -> ExpectStepDefinition:
    step = _object(raw, location)
    _reject_unknown(step, {"name", "expect"}, location)
    name = _optional_nonempty_string(step.get("name"), f"{location}.name")
    expect = _object(step.get("expect"), f"{location}.expect")
    _reject_unknown(
        expect,
        {
            "outcome",
            "responsePrompts",
            "connectedObservationSeconds",
            "maxLatencySeconds",
        },
        f"{location}.expect",
    )
    outcome_value = _nonempty_string(
        expect.get("outcome"), f"{location}.expect.outcome"
    )
    try:
        expected_outcome = ExpectedOutcome(outcome_value)
    except ValueError as error:
        allowed = ", ".join(outcome.value for outcome in ExpectedOutcome)
        raise TestPlanError(
            f"{location}.expect.outcome must be one of: {allowed}"
        ) from error

    expected_response_prompts = _positive_integer(
        expect.get("responsePrompts", 1),
        f"{location}.expect.responsePrompts",
    )
    connected_observation_seconds = _nonnegative_number(
        expect.get("connectedObservationSeconds", 0),
        f"{location}.expect.connectedObservationSeconds",
    )
    max_latency_seconds = (
        _positive_number(
            expect["maxLatencySeconds"],
            f"{location}.expect.maxLatencySeconds",
        )
        if "maxLatencySeconds" in expect
        else None
    )
    if (
        connected_observation_seconds > 0
        and expected_outcome != ExpectedOutcome.TRANSFER
    ):
        raise TestPlanError(
            f"{location}.expect.connectedObservationSeconds is only valid "
            "for transfer outcomes"
        )
    return ExpectStepDefinition(
        name=name,
        outcome=expected_outcome,
        response_prompts=expected_response_prompts,
        connected_observation_seconds=connected_observation_seconds,
        max_latency_seconds=max_latency_seconds,
    )


def _parse_use(raw: Any, location: str) -> dict[str, Any]:
    value = _object(raw, location)
    _reject_unknown(value, USE_FIELDS, location)
    parsed: dict[str, Any] = {}
    for field, raw_value in value.items():
        field_location = f"{location}.{field}"
        if field == "voice":
            parsed[field] = _nonempty_string(raw_value, field_location)
        elif field == "headless":
            if not isinstance(raw_value, bool):
                raise TestPlanError(f"{field_location} must be a boolean")
            parsed[field] = raw_value
        elif field in {"remoteSilenceMs", "remotePromptOccurrence"}:
            parsed[field] = _positive_integer(raw_value, field_location)
        elif field == "initialSilenceFallbackSeconds":
            parsed[field] = _nonnegative_number(raw_value, field_location)
        else:
            parsed[field] = _positive_number(raw_value, field_location)
    return parsed


def _object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TestPlanError(f"{location} must be a JSON object")
    return value


def _reject_unknown(value: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise TestPlanError(
            f"{location} contains unknown field(s): {', '.join(unknown)}"
        )


def _nonempty_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TestPlanError(f"{location} must be a non-empty string")
    return value


def _optional_nonempty_string(value: Any, location: str) -> str | None:
    return None if value is None else _nonempty_string(value, location)


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _positive_integer(value: Any, location: str) -> int:
    if not _is_integer(value) or value <= 0:
        raise TestPlanError(f"{location} must be an integer greater than zero")
    return value


def _number(value: Any, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TestPlanError(f"{location} must be a number")
    return float(value)


def _nonnegative_number(value: Any, location: str) -> float:
    number = _number(value, location)
    if number < 0:
        raise TestPlanError(f"{location} cannot be negative")
    return number


def _positive_number(value: Any, location: str) -> float:
    number = _number(value, location)
    if number <= 0:
        raise TestPlanError(f"{location} must be greater than zero")
    return number
