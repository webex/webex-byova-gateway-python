"""CLI entry point for the Python-orchestrated BYOVA E2E caller."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path
from typing import TypeVar

from .artifacts import redact_destination, write_artifact
from .audio import (
    AudioPreparationError,
    prepare_wav,
    render_text,
    render_text_sequence,
)
from .auth import (
    OAuthError,
    OAuthTokenStore,
    access_token_for_run,
    complete_login,
    default_token_path,
    load_local_environment,
)
from .models import ExpectedOutcome, RunConfig
from .plan import (
    TestDefinition,
    TestPlanError,
    load_plan,
    load_test,
)
from .runner import BrowserRunner, RunFailure

DESTINATION_PATTERN = re.compile(r"^(?:tel:)?\+?[0-9]{2,20}$")
TOOL_ROOT = Path(__file__).resolve().parents[2]
LEGACY_TOKEN_PATH = TOOL_ROOT / ".state" / "oauth-token.json"
T = TypeVar("T")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    login = commands.add_parser(
        "login", help="Authorize the dedicated Webex Calling test user"
    )
    login.add_argument("--timeout-seconds", type=float, default=300)

    validate = commands.add_parser(
        "validate", help="Validate a JSON test plan without placing a call"
    )
    validate.add_argument("--config", dest="config_file", type=Path, required=True)
    validate.add_argument(
        "--list",
        action="store_true",
        dest="list_tests",
        help="List test IDs and titles after validation",
    )

    run = commands.add_parser("run", help="Place one headless regression call")
    run.add_argument(
        "--destination", required=True, help="Extension or E.164 number to dial"
    )
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="Text rendered locally through macOS say")
    source.add_argument("--wav", type=Path, help="Existing WAV fixture to inject")
    source.add_argument(
        "--text-segment",
        action="append",
        dest="text_segments",
        help="Repeat for each locally rendered speech segment",
    )
    source.add_argument(
        "--test",
        dest="test_id",
        help="Run one named test and its assertions from the JSON test plan",
    )
    run.add_argument(
        "--config",
        dest="config_file",
        type=Path,
        default=None,
        help="Playwright-shaped JSON test plan used by --test",
    )
    run.add_argument(
        "--voice",
        default=None,
        help="macOS say voice; overrides the test plan or Samantha default",
    )
    run.add_argument(
        "--segment-pause-ms",
        type=int,
        default=None,
        help="Exact silence inserted between repeated --text-segment values",
    )
    run.add_argument("--remote-silence-ms", type=int, default=None)
    run.add_argument(
        "--remote-prompt-occurrence",
        type=int,
        default=None,
        help=(
            "Inject after this completed remote-audio epoch; use 2 when "
            "contact-center ringback precedes the virtual-agent greeting"
        ),
    )
    run.add_argument(
        "--initial-silence-fallback-seconds",
        type=float,
        default=None,
        help="Inject after this long with no observed remote speech; set to 0 to disable",
    )
    run.add_argument("--prompt-timeout-seconds", type=float, default=None)
    run.add_argument("--call-timeout-seconds", type=float, default=None)
    run.add_argument("--post-audio-grace-seconds", type=float, default=None)
    run.add_argument(
        "--require-remote-response",
        action="store_true",
        help="Fail unless remote audio responds after caller audio finishes",
    )
    run.add_argument("--response-timeout-seconds", type=float, default=None)
    run.add_argument(
        "--expect-outcome",
        choices=[outcome.value for outcome in ExpectedOutcome],
        help=(
            "Assert a normal response, successful session-end disconnect, or "
            "configured transfer announcement sequence"
        ),
    )
    run.add_argument(
        "--expected-response-prompts",
        type=int,
        default=None,
        help="Completed post-injection remote prompt epochs required",
    )
    run.add_argument(
        "--connected-observation-seconds",
        type=float,
        default=None,
        help=(
            "Optional transfer-specific interval during which the call must remain "
            "connected after all required announcements"
        ),
    )
    run.add_argument("--artifact-dir", type=Path, default=TOOL_ROOT / ".artifacts")
    browser_mode = run.add_mutually_exclusive_group()
    browser_mode.add_argument(
        "--headless",
        action="store_true",
        dest="headless",
        help="Run Chromium without opening a visible window (default)",
    )
    browser_mode.add_argument(
        "--headed",
        action="store_false",
        dest="headless",
        help="Open Chromium visibly for interactive media debugging",
    )
    run.set_defaults(headless=None)
    return parser


def main(argv: list[str] | None = None) -> None:
    load_local_environment(TOOL_ROOT / ".env")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "login":
            if args.timeout_seconds <= 0:
                raise CLIError("--timeout-seconds must be greater than zero")
            token_path = complete_login(_oauth_token_store(), args.timeout_seconds)
            print(f"Webex OAuth authorization saved locally at {token_path}")
            return
        if args.command == "validate":
            plan = load_plan(args.config_file)
            print(
                f"Validated {len(plan.tests)} test(s) from {plan.source_file} "
                f"(sha256: {plan.config_sha256})"
            )
            if args.list_tests:
                for selected_test in plan.tests:
                    print(f"{selected_test.test_id}: {selected_test.title}")
            return
        _run(args)
    except (
        AudioPreparationError,
        OAuthError,
        RunFailure,
        TestPlanError,
        CLIError,
    ) as error:
        if args.command == "run":
            event_history = [
                {
                    "name": event.name,
                    "timestamp": event.timestamp,
                    "received_at_utc": event.received_at_utc,
                    "details": event.details,
                }
                for event in getattr(error, "events", [])
            ]
            artifact = write_artifact(
                args.artifact_dir,
                {
                    "destination": redact_destination(args.destination),
                    "status": "failed",
                    "error": str(error),
                    "events": event_history,
                },
            )
            print(f"BYOVA E2E caller failed. Artifact: {artifact}", file=sys.stderr)
        elif args.command == "login":
            print(f"BYOVA E2E login failed: {error}", file=sys.stderr)
        else:
            print(f"BYOVA E2E config validation failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


class CLIError(ValueError):
    """A validated user-facing CLI input failure."""


def _oauth_token_store() -> OAuthTokenStore:
    return OAuthTokenStore(default_token_path(), legacy_path=LEGACY_TOKEN_PATH)


def _run(args: argparse.Namespace) -> None:
    if args.test_id and args.config_file is None:
        raise CLIError("--config is required with --test")
    if args.config_file is not None and not args.test_id:
        raise CLIError("--config is only valid with --test")
    selected_test = load_test(args.test_id, args.config_file) if args.test_id else None
    text = args.text if selected_test is None else selected_test.text
    text_segments = (
        args.text_segments
        if selected_test is None
        else list(selected_test.text_segments) or None
    )
    wav = args.wav if selected_test is None else selected_test.wav
    voice = _configured(args.voice, selected_test, "voice", "Samantha")
    segment_pause_ms = _configured(
        args.segment_pause_ms, selected_test, "segment_pause_ms", 1000
    )
    remote_silence_ms = _configured(
        args.remote_silence_ms, selected_test, "remote_silence_ms", 750
    )
    remote_prompt_occurrence = _configured(
        args.remote_prompt_occurrence,
        selected_test,
        "remote_prompt_occurrence",
        1,
    )
    initial_silence_fallback_seconds = _configured(
        args.initial_silence_fallback_seconds,
        selected_test,
        "initial_silence_fallback_seconds",
        10.0,
    )
    prompt_timeout_seconds = _configured(
        args.prompt_timeout_seconds,
        selected_test,
        "prompt_timeout_seconds",
        60.0,
    )
    call_timeout_seconds = _configured(
        args.call_timeout_seconds, selected_test, "call_timeout_seconds", 120.0
    )
    post_audio_grace_seconds = _configured(
        args.post_audio_grace_seconds,
        selected_test,
        "post_audio_grace_seconds",
        5.0,
    )
    response_timeout_seconds = _configured(
        args.response_timeout_seconds,
        selected_test,
        "response_timeout_seconds",
        30.0,
    )
    headless = _configured(args.headless, selected_test, "headless", True)
    expected_outcome = (
        ExpectedOutcome(args.expect_outcome)
        if args.expect_outcome
        else (selected_test.expected_outcome if selected_test else None)
    )
    expected_response_prompts = (
        args.expected_response_prompts
        if args.expected_response_prompts is not None
        else (selected_test.expected_response_prompts if selected_test else 1)
    )
    connected_observation_seconds = (
        args.connected_observation_seconds
        if args.connected_observation_seconds is not None
        else (selected_test.connected_observation_seconds if selected_test else 0.0)
    )

    if not DESTINATION_PATTERN.fullmatch(args.destination):
        raise CLIError(
            "--destination must be an extension or E.164 number, optionally prefixed with tel:"
        )
    if remote_silence_ms <= 0:
        raise CLIError("--remote-silence-ms must be greater than zero")
    if remote_prompt_occurrence <= 0:
        raise CLIError("--remote-prompt-occurrence must be greater than zero")
    if (
        min(
            prompt_timeout_seconds,
            call_timeout_seconds,
            post_audio_grace_seconds,
            response_timeout_seconds,
        )
        <= 0
    ):
        raise CLIError("All timeout values must be greater than zero")
    if initial_silence_fallback_seconds < 0:
        raise CLIError("--initial-silence-fallback-seconds cannot be negative")
    if connected_observation_seconds < 0:
        raise CLIError("--connected-observation-seconds cannot be negative")
    if expected_response_prompts <= 0:
        raise CLIError("--expected-response-prompts must be greater than zero")
    if text_segments is not None:
        if len(text_segments) < 2:
            raise CLIError("Repeat --text-segment at least twice")
        if segment_pause_ms <= 0:
            raise CLIError("--segment-pause-ms must be greater than zero")

    token = access_token_for_run(_oauth_token_store())
    with tempfile.TemporaryDirectory(prefix="byova-e2e-") as temp_dir:
        audio_path = Path(temp_dir) / "caller.wav"
        if text is not None:
            prepared = render_text(text, voice, audio_path)
            audio_profile = {"kind": "text"}
        elif text_segments is not None:
            prepared = render_text_sequence(
                text_segments,
                segment_pause_ms,
                voice,
                audio_path,
            )
            audio_profile = {
                "kind": "segmented_text",
                "segment_count": len(text_segments),
                "segment_pause_ms": segment_pause_ms,
            }
        else:
            prepared = prepare_wav(wav, audio_path)
            audio_profile = {"kind": "wav"}
        config = RunConfig(
            destination=args.destination,
            access_token=token,
            audio_path=prepared.path,
            audio_sha256=prepared.sha256,
            audio_duration_seconds=prepared.duration_seconds,
            remote_silence_seconds=remote_silence_ms / 1000,
            initial_silence_fallback_seconds=initial_silence_fallback_seconds,
            prompt_timeout_seconds=prompt_timeout_seconds,
            call_timeout_seconds=call_timeout_seconds,
            post_audio_grace_seconds=post_audio_grace_seconds,
            remote_prompt_occurrence=remote_prompt_occurrence,
            require_remote_response=args.require_remote_response,
            response_timeout_seconds=response_timeout_seconds,
            expected_outcome=expected_outcome,
            expected_response_prompts=expected_response_prompts,
            connected_observation_seconds=connected_observation_seconds,
            headless=headless,
        )
        result = BrowserRunner(TOOL_ROOT, config).run()

    artifact = write_artifact(
        args.artifact_dir,
        {
            "destination": redact_destination(args.destination),
            "status": "completed",
            "audio_sha256": config.audio_sha256,
            "audio_duration_seconds": config.audio_duration_seconds,
            "audio_profile": audio_profile,
            "prompt_profile": {
                "remote_prompt_occurrence": config.remote_prompt_occurrence,
                "remote_silence_ms": round(config.remote_silence_seconds * 1000),
            },
            "browser_profile": {"headless": config.headless},
            "test": selected_test.test_id if selected_test else None,
            "test_title": selected_test.title if selected_test else None,
            "config_file": (str(selected_test.source_file) if selected_test else None),
            "config_sha256": (selected_test.config_sha256 if selected_test else None),
            "expected_outcome": (
                config.expected_outcome.value if config.expected_outcome else None
            ),
            "expected_response_prompts": config.expected_response_prompts,
            **result,
        },
    )
    print(f"BYOVA E2E caller completed. Artifact: {artifact}")


def _configured(
    cli_value: T | None,
    selected_test: TestDefinition | None,
    test_field: str,
    default: T,
) -> T:
    """Apply explicit CLI, test plan, then built-in precedence."""
    if cli_value is not None:
        return cli_value
    if selected_test is not None:
        test_value = getattr(selected_test, test_field)
        if test_value is not None:
            return test_value
    return default
