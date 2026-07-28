from byova_e2e.cli import build_parser
from byova_e2e.models import ExpectedOutcome
from byova_e2e.scenarios import get_scenario


def test_live_runs_are_headless_by_default() -> None:
    args = build_parser().parse_args(
        ["run", "--destination", "9999", "--text", "hello"]
    )

    assert args.headless


def test_headed_mode_is_an_explicit_debug_opt_in() -> None:
    args = build_parser().parse_args(
        ["run", "--destination", "9999", "--text", "hello", "--headed"]
    )

    assert not args.headless


def test_named_scenario_is_a_complete_audio_source() -> None:
    args = build_parser().parse_args(
        ["run", "--destination", "9999", "--scenario", "task-complete"]
    )

    assert args.scenario == "task-complete"
    assert args.text is None
    assert args.text_segments is None


def test_terminal_scenarios_encode_distinct_observable_outcomes() -> None:
    completion = get_scenario("task-complete")
    transfer = get_scenario("transfer")

    assert completion.expected_outcome == ExpectedOutcome.SESSION_END
    assert completion.expected_response_prompts == 1
    assert transfer.expected_outcome == ExpectedOutcome.TRANSFER
    assert transfer.expected_response_prompts == 2


def test_natural_pause_scenario_keeps_one_turn_fixture() -> None:
    scenario = get_scenario("natural-pause")

    assert scenario.text_segments == (
        "I'd like to book",
        "a room in San Jose",
    )
    assert scenario.segment_pause_ms == 1800
