from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.exists() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _run_dreaming(args: argparse.Namespace) -> int:
    from hermes_dreaming.cli import main as dreaming_main

    dream_args = list(getattr(args, "dreaming_args", []) or [])
    if dream_args[:1] == ["--"]:
        dream_args = dream_args[1:]
    if not dream_args:
        dream_args = ["--help"]

    try:
        result = dreaming_main(dream_args)
    except SystemExit as exc:
        code = exc.code
        if isinstance(code, int):
            return code
        return 0 if code in (None, "") else 1

    return int(result or 0)


def _setup_dreaming_cli(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "dreaming_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to the dreaming CLI.",
    )


def register(ctx) -> None:
    ctx.register_cli_command(
        name="dreaming",
        help="Run the hermes-dreaming staged self-improvement engine",
        setup_fn=_setup_dreaming_cli,
        handler_fn=_run_dreaming,
        description=(
            "Expose the standalone hermes-dreaming CLI inside Hermes. "
            "Use it to create, inspect, validate, apply, or discard staged self-improvement artifacts."
        ),
    )

    skill_md = ROOT / "skills" / "hermes-dreaming" / "SKILL.md"
    if skill_md.exists():
        ctx.register_skill("dreaming", skill_md)
