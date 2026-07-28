from byova_e2e.cli import build_parser


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
