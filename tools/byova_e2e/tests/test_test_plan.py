import json
from hashlib import sha256
from pathlib import Path

import pytest
from byova_e2e.models import ExpectedOutcome
from byova_e2e.plan import (
    ExpectStepDefinition,
    InputStepDefinition,
    load_plan,
    load_test,
)
from byova_e2e.plan import (
    TestPlanError as PlanError,
)


def _write_plan(
    tmp_path: Path,
    *,
    steps: list[dict[str, object]] | None = None,
    root_updates: dict[str, object] | None = None,
    test_updates: dict[str, object] | None = None,
) -> Path:
    plan: dict[str, object] = {
        "version": 1,
        "use": {
            "headless": True,
            "voice": "Alex",
            "remotePromptOccurrence": 2,
            "requireGatewayEvents": True,
        },
        "tests": [
            {
                "id": "sample",
                "title": "runs a sample request",
                "steps": steps
                or [
                    {
                        "name": "Speak",
                        "action": "speak",
                        "text": "Hello",
                    },
                    {
                        "name": "Assert",
                        "expect": {
                            "outcome": "response",
                            "responsePrompts": 1,
                        },
                    },
                ],
            }
        ],
    }
    if root_updates:
        plan.update(root_updates)
    if test_updates:
        tests = plan["tests"]
        assert isinstance(tests, list)
        test = tests[0]
        assert isinstance(test, dict)
        test.update(test_updates)
    path = tmp_path / "sample.spec.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


def test_loads_playwright_shaped_defaults_and_test_override(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        test_updates={
            "use": {
                "voice": "Samantha",
                "responseTimeoutSeconds": 45,
            }
        },
    )

    selected_test = load_test("sample", path)

    assert selected_test.text == "Hello"
    assert selected_test.voice == "Samantha"
    assert selected_test.headless
    assert selected_test.remote_prompt_occurrence == 2
    assert selected_test.response_timeout_seconds == 45
    assert selected_test.require_gateway_events is True
    assert selected_test.expected_outcome == ExpectedOutcome.RESPONSE


def test_load_plan_records_order_and_content_hash(tmp_path: Path) -> None:
    path = _write_plan(tmp_path)

    plan = load_plan(path)

    assert [test.test_id for test in plan.tests] == ["sample"]
    assert plan.config_sha256 == sha256(path.read_bytes()).hexdigest()
    assert plan.tests[0].config_sha256 == plan.config_sha256


def test_resolves_play_fixture_relative_to_config(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        steps=[
            {"action": "play", "path": "fixtures/request.wav"},
            {"expect": {"outcome": "response"}},
        ],
    )

    selected_test = load_test("sample", path)

    assert selected_test.wav == (tmp_path / "fixtures/request.wav").resolve()


def test_loads_ordered_multi_injection_steps(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        steps=[
            {"action": "speak", "text": "I need a hotel."},
            {"expect": {"outcome": "response"}},
            {"action": "speak", "text": "A queen room, please."},
            {"expect": {"outcome": "response"}},
        ],
    )

    selected_test = load_test("sample", path)

    assert selected_test.steps == (
        InputStepDefinition(text="I need a hotel."),
        ExpectStepDefinition(outcome=ExpectedOutcome.RESPONSE),
        InputStepDefinition(text="A queen room, please."),
        ExpectStepDefinition(outcome=ExpectedOutcome.RESPONSE),
    )


def test_loads_response_start_gate_for_speaking_during_playback(
    tmp_path: Path,
) -> None:
    path = _write_plan(
        tmp_path,
        steps=[
            {"action": "speak", "text": "Tell me about the room."},
            {"expect": {"outcome": "response-start"}},
            {"action": "speak", "text": "I also need late checkout."},
            {"expect": {"outcome": "response"}},
        ],
    )

    selected_test = load_test("sample", path)

    assert selected_test.steps[1] == ExpectStepDefinition(
        outcome=ExpectedOutcome.RESPONSE_START
    )


def test_loads_per_expectation_latency_target(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        steps=[
            {"action": "speak", "text": "Hello"},
            {
                "expect": {
                    "outcome": "response",
                    "maxLatencySeconds": 6.0,
                }
            },
        ],
    )

    selected_test = load_test("sample", path)

    assert selected_test.steps[1] == ExpectStepDefinition(
        outcome=ExpectedOutcome.RESPONSE,
        max_latency_seconds=6.0,
    )


def test_rejects_nonpositive_latency_target(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        steps=[
            {"action": "speak", "text": "Hello"},
            {
                "expect": {
                    "outcome": "response",
                    "maxLatencySeconds": 0,
                }
            },
        ],
    )

    with pytest.raises(PlanError, match="maxLatencySeconds must be greater than zero"):
        load_test("sample", path)


def test_rejects_consecutive_actions_without_an_expectation(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        steps=[
            {"action": "speak", "text": "First"},
            {"action": "speak", "text": "Second"},
            {"expect": {"outcome": "response"}},
        ],
    )

    with pytest.raises(PlanError, match="must alternate audio actions and expectations"):
        load_test("sample", path)


def test_rejects_unknown_fields_to_catch_misspellings(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        root_updates={"uses": {"headless": True}},
    )

    with pytest.raises(PlanError, match=r"unknown field\(s\): uses"):
        load_test("sample", path)


def test_rejects_unsupported_version(tmp_path: Path) -> None:
    path = _write_plan(tmp_path, root_updates={"version": 2})

    with pytest.raises(PlanError, match="version must be 1"):
        load_test("sample", path)


def test_rejects_unknown_test_with_available_ids(tmp_path: Path) -> None:
    path = _write_plan(tmp_path)

    with pytest.raises(PlanError, match="Available: sample"):
        load_test("missing", path)


def test_rejects_duplicate_test_ids(tmp_path: Path) -> None:
    path = _write_plan(tmp_path)
    plan = json.loads(path.read_text(encoding="utf-8"))
    plan["tests"].append(plan["tests"][0])
    path.write_text(json.dumps(plan), encoding="utf-8")

    with pytest.raises(PlanError, match="Duplicate test id"):
        load_test("sample", path)


def test_rejects_step_order_that_runner_cannot_execute(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        steps=[
            {"expect": {"outcome": "response"}},
            {"action": "speak", "text": "Hello"},
        ],
    )

    with pytest.raises(PlanError, match=r"unknown field\(s\): expect"):
        load_test("sample", path)


def test_rejects_connected_observation_for_non_transfer(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        steps=[
            {"action": "speak", "text": "Hello"},
            {
                "expect": {
                    "outcome": "response",
                    "connectedObservationSeconds": 5,
                }
            },
        ],
    )

    with pytest.raises(PlanError, match="only valid for transfer"):
        load_test("sample", path)


def test_rejects_boolean_where_positive_number_is_required(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        root_updates={"use": {"responseTimeoutSeconds": True}},
    )

    with pytest.raises(PlanError, match="must be a number"):
        load_test("sample", path)
