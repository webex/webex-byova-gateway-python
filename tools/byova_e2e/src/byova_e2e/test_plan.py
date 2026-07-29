"""Load Playwright-shaped, data-driven live-call test plans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import ExpectedOutcome

DEFAULT_CONFIG_FILE = (
    Path(__file__).resolve().parents[2] / "config" / "gecx-regression.spec.json"
)
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
class TestDefinition:
    """One selected test after top-level and test-level settings are merged."""

    test_id: str
    title: str
    description: str
    source_file: Path
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


def load_test(test_id: str, config_file: Path = DEFAULT_CONFIG_FILE) -> TestDefinition:
    """Load one named test from a versioned JSON test plan."""
    path = config_file.expanduser().resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise TestPlanError(f"Test config does not exist: {path}") from error
    except OSError as error:
        raise TestPlanError(f"Unable to read test config {path}: {error}") from error
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

    parsed_tests: dict[str, TestDefinition] = {}
    for index, test in enumerate(tests):
        parsed = _parse_test(test, index, path, shared_use)
        if parsed.test_id in parsed_tests:
            raise TestPlanError(f"Duplicate test id: {parsed.test_id!r}")
        parsed_tests[parsed.test_id] = parsed

    if test_id not in parsed_tests:
        available = ", ".join(sorted(parsed_tests))
        raise TestPlanError(
            f"Unknown test {test_id!r} in {path}. Available: {available}"
        )
    return parsed_tests[test_id]


def _parse_test(
    raw: Any,
    index: int,
    source_file: Path,
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

    steps = value.get("steps")
    if not isinstance(steps, list) or len(steps) != 2:
        raise TestPlanError(
            f"{location}.steps must contain one audio action followed by one expect step"
        )
    input_values = _parse_input_step(steps[0], f"{location}.steps[0]", source_file)
    expectation_values = _parse_expect_step(steps[1], f"{location}.steps[1]")

    return TestDefinition(
        test_id=test_id,
        title=title,
        description=description or title,
        source_file=source_file,
        **input_values,
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
        **expectation_values,
    )


def _parse_input_step(raw: Any, location: str, source_file: Path) -> dict[str, Any]:
    step = _object(raw, location)
    _reject_unknown(
        step,
        {"name", "action", "text", "segments", "pauseMs", "path"},
        location,
    )
    _optional_nonempty_string(step.get("name"), f"{location}.name")
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
            return {
                "text": _nonempty_string(step["text"], f"{location}.text"),
            }
        segments = step["segments"]
        if not isinstance(segments, list) or len(segments) < 2:
            raise TestPlanError(
                f"{location}.segments must contain at least two strings"
            )
        return {
            "text_segments": tuple(
                _nonempty_string(segment, f"{location}.segments[{index}]")
                for index, segment in enumerate(segments)
            ),
            "segment_pause_ms": _positive_integer(
                step.get("pauseMs"), f"{location}.pauseMs"
            ),
        }
    if action == "play":
        if any(field in step for field in ("text", "segments", "pauseMs")):
            raise TestPlanError(
                f"{location} with action 'play' only accepts name, action, and path"
            )
        wav_value = _nonempty_string(step.get("path"), f"{location}.path")
        wav = Path(wav_value).expanduser()
        if not wav.is_absolute():
            wav = source_file.parent / wav
        return {"wav": wav.resolve()}
    raise TestPlanError(f"{location}.action must be 'speak' or 'play'")


def _parse_expect_step(raw: Any, location: str) -> dict[str, Any]:
    step = _object(raw, location)
    _reject_unknown(step, {"name", "expect"}, location)
    _optional_nonempty_string(step.get("name"), f"{location}.name")
    expect = _object(step.get("expect"), f"{location}.expect")
    _reject_unknown(
        expect,
        {"outcome", "responsePrompts", "connectedObservationSeconds"},
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
    if (
        connected_observation_seconds > 0
        and expected_outcome != ExpectedOutcome.TRANSFER
    ):
        raise TestPlanError(
            f"{location}.expect.connectedObservationSeconds is only valid "
            "for transfer outcomes"
        )
    return {
        "expected_outcome": expected_outcome,
        "expected_response_prompts": expected_response_prompts,
        "connected_observation_seconds": connected_observation_seconds,
    }


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
