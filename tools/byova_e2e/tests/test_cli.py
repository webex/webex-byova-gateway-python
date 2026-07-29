from byova_e2e.cli import build_parser
from byova_e2e.models import ExpectedOutcome
from byova_e2e.test_plan import load_test


def test_live_runs_have_no_cli_browser_override_by_default() -> None:
    args = build_parser().parse_args(
        ["run", "--destination", "9999", "--text", "hello"]
    )

    assert args.headless is None


def test_headed_mode_is_an_explicit_debug_opt_in() -> None:
    args = build_parser().parse_args(
        ["run", "--destination", "9999", "--text", "hello", "--headed"]
    )

    assert not args.headless


def test_named_test_is_a_complete_audio_source() -> None:
    args = build_parser().parse_args(
        ["run", "--destination", "9999", "--test", "task-complete"]
    )

    assert args.test_id == "task-complete"
    assert args.text is None
    assert args.text_segments is None


def test_scenario_alias_remains_available() -> None:
    args = build_parser().parse_args(
        ["run", "--destination", "9999", "--scenario", "task-complete"]
    )

    assert args.test_id == "task-complete"


def test_terminal_tests_encode_distinct_observable_outcomes() -> None:
    completion = load_test("task-complete")
    transfer = load_test("transfer")

    assert completion.expected_outcome == ExpectedOutcome.SESSION_END
    assert completion.expected_response_prompts == 1
    assert transfer.expected_outcome == ExpectedOutcome.TRANSFER
    assert transfer.expected_response_prompts == 2


def test_natural_pause_test_keeps_one_turn_fixture() -> None:
    selected_test = load_test("natural-pause")

    assert selected_test.text_segments == (
        "I'd like to book",
        "a room in San Jose",
    )
    assert selected_test.segment_pause_ms == 1800
    assert selected_test.headless
    assert selected_test.remote_prompt_occurrence == 2
