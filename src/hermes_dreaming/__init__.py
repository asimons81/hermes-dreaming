"""Hermes Dreaming, staged self-improvement for memory, skills, and facts."""

from __future__ import annotations

import argparse
import contextlib
import io
import shlex
from pathlib import Path

from . import session_reader
from .artifact import DreamArtifact, DreamProposal, SourceSnapshot

__all__ = ["DreamArtifact", "DreamProposal", "SourceSnapshot", "__version__", "register", "session_reader"]
__version__ = "0.2.0"


def _repo_root() -> Path:
    """Best-effort repo root lookup for bundled resources."""

    here = Path(__file__).resolve()
    for parent in here.parents:
        skill_path = parent / "skills" / "hermes-dreaming" / "SKILL.md"
        if skill_path.exists():
            return parent
    return here.parents[2]


def _skill_path() -> Path:
    return _repo_root() / "skills" / "hermes-dreaming" / "SKILL.md"


def _normalize_dreaming_args(raw_args: list[str] | tuple[str, ...] | None) -> list[str]:
    dream_args = list(raw_args or [])
    if dream_args[:1] == ["--"]:
        dream_args = dream_args[1:]
    if not dream_args:
        dream_args = ["--help"]
    return dream_args


def _invoke_dreaming_main(raw_args: list[str] | tuple[str, ...] | None) -> int:
    from .cli import main as dreaming_main

    try:
        result = dreaming_main(_normalize_dreaming_args(raw_args))
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


def _run_dreaming_cli(args: argparse.Namespace) -> int:
    code = _invoke_dreaming_main(list(getattr(args, "dreaming_args", []) or []))
    if code:
        raise SystemExit(code)
    return 0


def _run_dreaming_slash(raw_args: str) -> str:
    tokens = shlex.split(raw_args) if raw_args else []
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        code = _invoke_dreaming_main(tokens)
    output = buffer.getvalue().strip()
    if output:
        return output
    if code == 0:
        return "Hermes Dreaming finished."
    return f"Hermes Dreaming exited with status {code}."


def register(ctx) -> None:
    """Register the Hermes Dreaming CLI command, slash command, and skill."""

    ctx.register_cli_command(
        name="dreaming",
        help="Run the hermes-dreaming staged self-improvement engine",
        setup_fn=_setup_dreaming_cli,
        handler_fn=_run_dreaming_cli,
        description=(
            "Expose the standalone hermes-dreaming CLI inside Hermes. "
            "Use it to create, inspect, validate, apply, or discard staged self-improvement artifacts."
        ),
    )

    ctx.register_command(
        name="dreaming",
        handler=_run_dreaming_slash,
        description=(
            "Route Hermes Dreaming artifact commands through the chat surface "
            "without mutating live state until apply time."
        ),
        args_hint="create|review|summarize|approve|reject|diff|validate|apply|discard|compact|install-cron|status|update",
    )

    skill_md = _skill_path()
    if skill_md.exists():
        ctx.register_skill("dreaming", skill_md)
