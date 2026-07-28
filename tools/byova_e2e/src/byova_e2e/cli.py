"""CLI entry point for the Python-orchestrated BYOVA E2E caller."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

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
    load_local_environment,
)
from .models import RunConfig
from .runner import BrowserRunner, RunFailure

DESTINATION_PATTERN = re.compile(r"^(?:tel:)?\+?[0-9]{2,20}$")
TOOL_ROOT = Path(__file__).resolve().parents[2]
TOKEN_PATH = TOOL_ROOT / ".state" / "oauth-token.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    login = commands.add_parser(
        "login", help="Authorize the dedicated Webex Calling test user"
    )
    login.add_argument("--timeout-seconds", type=float, default=300)

    run = commands.add_parser(
        "run", help="Place one test call and inject one utterance"
    )
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
    run.add_argument("--voice", default="Samantha", help="macOS say voice for --text")
    run.add_argument(
        "--segment-pause-ms",
        type=int,
        default=1000,
        help="Exact silence inserted between repeated --text-segment values",
    )
    run.add_argument("--remote-silence-ms", type=int, default=750)
    run.add_argument(
        "--remote-prompt-occurrence",
        type=int,
        default=1,
        help=(
            "Inject after this completed remote-audio epoch; use 2 when "
            "contact-center ringback precedes the virtual-agent greeting"
        ),
    )
    run.add_argument(
        "--initial-silence-fallback-seconds",
        type=float,
        default=10,
        help="Inject after this long with no observed remote speech; set to 0 to disable",
    )
    run.add_argument("--prompt-timeout-seconds", type=float, default=60)
    run.add_argument("--call-timeout-seconds", type=float, default=120)
    run.add_argument("--post-audio-grace-seconds", type=float, default=5)
    run.add_argument(
        "--require-remote-response",
        action="store_true",
        help="Fail unless remote audio responds after caller audio finishes",
    )
    run.add_argument("--response-timeout-seconds", type=float, default=30)
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
    run.set_defaults(headless=True)
    return parser


def main(argv: list[str] | None = None) -> None:
    load_local_environment(TOOL_ROOT / ".env")
    args = build_parser().parse_args(argv)
    try:
        if args.command == "login":
            if args.timeout_seconds <= 0:
                raise CLIError("--timeout-seconds must be greater than zero")
            token_path = complete_login(
                OAuthTokenStore(TOKEN_PATH), args.timeout_seconds
            )
            print(f"Webex OAuth authorization saved locally at {token_path}")
            return
        _run(args)
    except (AudioPreparationError, OAuthError, RunFailure, CLIError) as error:
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
        else:
            print(f"BYOVA E2E login failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


class CLIError(ValueError):
    """A validated user-facing CLI input failure."""


def _run(args: argparse.Namespace) -> None:
    if not DESTINATION_PATTERN.fullmatch(args.destination):
        raise CLIError(
            "--destination must be an extension or E.164 number, optionally prefixed with tel:"
        )
    if args.remote_silence_ms <= 0:
        raise CLIError("--remote-silence-ms must be greater than zero")
    if args.remote_prompt_occurrence <= 0:
        raise CLIError("--remote-prompt-occurrence must be greater than zero")
    if (
        min(
            args.prompt_timeout_seconds,
            args.call_timeout_seconds,
            args.post_audio_grace_seconds,
            args.response_timeout_seconds,
        )
        <= 0
    ):
        raise CLIError("All timeout values must be greater than zero")
    if args.initial_silence_fallback_seconds < 0:
        raise CLIError("--initial-silence-fallback-seconds cannot be negative")
    if args.text_segments is not None:
        if len(args.text_segments) < 2:
            raise CLIError("Repeat --text-segment at least twice")
        if args.segment_pause_ms <= 0:
            raise CLIError("--segment-pause-ms must be greater than zero")

    token = access_token_for_run(OAuthTokenStore(TOKEN_PATH))
    with tempfile.TemporaryDirectory(prefix="byova-e2e-") as temp_dir:
        audio_path = Path(temp_dir) / "caller.wav"
        if args.text is not None:
            prepared = render_text(args.text, args.voice, audio_path)
            audio_profile = {"kind": "text"}
        elif args.text_segments is not None:
            prepared = render_text_sequence(
                args.text_segments,
                args.segment_pause_ms,
                args.voice,
                audio_path,
            )
            audio_profile = {
                "kind": "segmented_text",
                "segment_count": len(args.text_segments),
                "segment_pause_ms": args.segment_pause_ms,
            }
        else:
            prepared = prepare_wav(args.wav, audio_path)
            audio_profile = {"kind": "wav"}
        config = RunConfig(
            destination=args.destination,
            access_token=token,
            audio_path=prepared.path,
            audio_sha256=prepared.sha256,
            audio_duration_seconds=prepared.duration_seconds,
            remote_silence_seconds=args.remote_silence_ms / 1000,
            initial_silence_fallback_seconds=args.initial_silence_fallback_seconds,
            prompt_timeout_seconds=args.prompt_timeout_seconds,
            call_timeout_seconds=args.call_timeout_seconds,
            post_audio_grace_seconds=args.post_audio_grace_seconds,
            remote_prompt_occurrence=args.remote_prompt_occurrence,
            require_remote_response=args.require_remote_response,
            response_timeout_seconds=args.response_timeout_seconds,
            headless=args.headless,
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
            **result,
        },
    )
    print(f"BYOVA E2E caller completed. Artifact: {artifact}")
