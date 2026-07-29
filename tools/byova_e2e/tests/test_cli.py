import json
from pathlib import Path

import pytest
from byova_e2e.audio import PreparedAudio
from byova_e2e.cli import CLIError, _run, build_parser, main
from byova_e2e.models import ExpectedOutcome, RunAction, RunExpectation


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
        [
            "run",
            "--destination",
            "9999",
            "--config",
            "connector.spec.json",
            "--test",
            "request-response",
        ]
    )

    assert args.test_id == "request-response"
    assert args.config_file == Path("connector.spec.json")
    assert args.text is None
    assert args.text_segments is None


def test_named_test_requires_an_explicit_config() -> None:
    args = build_parser().parse_args(
        ["run", "--destination", "9999", "--test", "request-response"]
    )

    with pytest.raises(CLIError, match="--config is required with --test"):
        _run(args)


def test_validate_can_list_tests_without_run_inputs() -> None:
    args = build_parser().parse_args(
        ["validate", "--config", "connector.spec.json", "--list"]
    )

    assert args.command == "validate"
    assert args.config_file == Path("connector.spec.json")
    assert args.list_tests


def test_validate_lists_plan_without_authentication(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = tmp_path / "connector.spec.json"
    config.write_text(
        json.dumps(
            {
                "version": 1,
                "tests": [
                    {
                        "id": "request-response",
                        "title": "receives one response",
                        "steps": [
                            {"action": "speak", "text": "Hello"},
                            {"expect": {"outcome": "response"}},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    main(["validate", "--config", str(config), "--list"])

    output = capsys.readouterr().out
    assert "Validated 1 test(s)" in output
    assert "request-response: receives one response" in output
    assert "sha256:" in output


def test_named_multi_turn_test_prepares_every_action(
    tmp_path: Path, monkeypatch
) -> None:
    config_file = tmp_path / "connector.spec.json"
    config_file.write_text(
        json.dumps(
            {
                "version": 1,
                "tests": [
                    {
                        "id": "multi-turn",
                        "title": "completes two turns",
                        "steps": [
                            {"action": "speak", "text": "I need a hotel."},
                            {"expect": {"outcome": "response"}},
                            {
                                "action": "speak",
                                "text": "A queen room, please.",
                            },
                            {"expect": {"outcome": "response"}},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    rendered_text: list[str] = []
    captured_config = None

    def fake_render_text(text, _voice, output_path):
        rendered_text.append(text)
        output_path.write_bytes(text.encode())
        return PreparedAudio(output_path, str(len(rendered_text)) * 64, 1)

    class FakeRunner:
        def __init__(self, _tool_root, config):
            nonlocal captured_config
            captured_config = config

        def run(self):
            return {}

    monkeypatch.setattr("byova_e2e.cli.render_text", fake_render_text)
    monkeypatch.setattr("byova_e2e.cli.access_token_for_run", lambda _store: "token")
    monkeypatch.setattr("byova_e2e.cli.BrowserRunner", FakeRunner)
    monkeypatch.setattr(
        "byova_e2e.cli.write_artifact",
        lambda _directory, _payload: tmp_path / "artifact.json",
    )
    args = build_parser().parse_args(
        [
            "run",
            "--destination",
            "9999",
            "--config",
            str(config_file),
            "--test",
            "multi-turn",
        ]
    )

    _run(args)

    assert rendered_text == ["I need a hotel.", "A queen room, please."]
    assert captured_config is not None
    assert len(captured_config.prepared_audio()) == 2
    assert captured_config.steps == (
        RunAction(0),
        RunExpectation(ExpectedOutcome.RESPONSE),
        RunAction(1),
        RunExpectation(ExpectedOutcome.RESPONSE),
    )
