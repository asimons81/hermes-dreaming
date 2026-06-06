from __future__ import annotations

import argparse
from datetime import timedelta
import os
from pathlib import Path

from .analyze import DreamRunConfig, create_dream_artifact, render_report_card_json, render_report_card_markdown
from .artifact import load_artifact
from .apply import (
    DreamApplyError,
    DreamRevertError,
    apply_artifact,
    discard_artifact,
    parse_filter_list,
    revert_artifact,
    validate_priority_filter,
    validate_target_kind_filter,
)
from .commands.compact import handle as compact_artifacts
from .commands.install_cron import handle as install_cron_command
from .commands.harvest import harvest_recent
from .commands.inbox import build_inbox, parse_filter, render_inbox, render_inbox_json
from .commands.digest import build_digest, build_inbox_digest, render_digest, render_inbox_digest
from .commands.report_card import handle as report_card_command
from .commands.review import (
    ReviewError,
    approve_artifact,
    handle as review_artifact,
    render_open_brief,
    render_summary,
    reject_artifact,
)
from .commands.status import build_status_snapshot, render_status
from .commands.update import handle as update_command, render_update_result
from .diffing import render_artifact_diff
from .providers import list_providers, render_providers_table
from .state import record_run
from .validation import validate_artifact


def _discover_update_repo_root() -> Path:
    env_root = os.environ.get("HERMES_DREAMING_REPO_ROOT")
    if env_root:
        candidate = Path(env_root).expanduser()
        if (candidate / "pyproject.toml").exists() and (candidate / "plugin.yaml").exists():
            return candidate

    canonical = Path("/home/tony/projects/hermes-dreaming")
    if (canonical / "pyproject.toml").exists() and (canonical / "plugin.yaml").exists():
        return canonical

    return Path(__file__).resolve().parents[2]


def _add_creation_arguments(parser: argparse.ArgumentParser, *, required_source: bool = True) -> None:
    parser.add_argument("--live-root", type=Path, default=Path.cwd(), help="Root of the live workspace")
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=Path.cwd() / ".dreaming" / "artifacts",
        help="Where artifacts are stored",
    )
    parser.add_argument("--source", action="append", required=False, type=Path, help="Source file or directory to scan")
    parser.add_argument("--recent", type=int, default=None, help="Harvest N recent local Hermes sessions into a source bundle before staging (alias for --from-sessions)")
    parser.add_argument("--from-sessions", dest="from_sessions", type=int, default=None, help="Harvest N recent local Hermes sessions into a source bundle before staging")
    parser.add_argument(
        "--from-since",
        dest="from_since",
        default=None,
        help="Time window for --from-sessions: e.g. '7d', '12h', '2w'. Suffix h/d/w. Capped at 50 sessions.",
    )
    parser.add_argument("--harvest-out", type=Path, default=None, help="Optional output path for the --from-sessions / --recent source bundle")
    parser.add_argument("--provider", default="offline-marker", help="Analysis provider to use (or 'offline-marker' when --no-llm is set)")
    parser.add_argument("--no-llm", dest="no_llm", action="store_true", help="Shorthand for --provider offline-marker (skip any external LLM)")
    parser.add_argument("--model", default=None, help="Optional provider model name")
    parser.add_argument("--api-key", default=None, help="Optional provider API key")
    parser.add_argument("--base-url", default=None, help="Optional provider base URL")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dreaming", description="Hermes Dreaming MVP")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="Create a staged dream artifact")
    _add_creation_arguments(create)

    harvest = sub.add_parser("harvest", help="Harvest recent local Hermes sessions into a bounded source bundle")
    harvest.add_argument("--recent", type=int, default=10, help="Number of recent sessions to harvest")
    harvest.add_argument("--out", type=Path, default=None, help="Output path for the harvested source bundle")
    harvest.add_argument("--db-path", type=Path, default=None, help="Optional Hermes session DB path for tests or alternate homes")
    harvest.add_argument("--state-path", type=Path, default=None, help="Optional Dreaming state path for pointer-log fallback")
    harvest.add_argument("--max-chars", type=int, default=8000, help="Maximum characters in the harvested bundle")

    inbox = sub.add_parser("inbox", help="Show the staged artifact review queue")
    inbox.add_argument("--artifact-root", type=Path, default=Path.cwd() / ".dreaming" / "artifacts", help="Where artifacts are stored")
    inbox.add_argument("--state", default=None, help="Comma-separated inbox states to include")
    inbox.add_argument("--priority", default=None, help="Comma-separated priority values to include")
    inbox.add_argument("--limit", type=int, default=None, help="Maximum inbox rows to show")
    inbox.add_argument("--apply-ready", dest="apply_ready", action="store_true", help="Filter to artifacts ready to apply (approved, no pending blockers)")
    inbox.add_argument("--json", action="store_true", help="Emit machine-readable JSON")

    review = sub.add_parser("review", help="Create a staged artifact or open an existing one")
    review.add_argument(
        "--open",
        dest="open_artifact",
        type=Path,
        default=None,
        help="Open an existing artifact instead of staging a new one",
    )
    _add_creation_arguments(review, required_source=False)

    summarize = sub.add_parser("summarize", help="Print a concise decision brief for an artifact")
    summarize.add_argument("artifact", type=Path, help="Artifact directory")

    approve = sub.add_parser("approve", help="Record approvals in artifact metadata without applying")
    approve.add_argument("artifact", type=Path, help="Artifact directory")
    approve.add_argument("proposal", help="Proposal id or 'all'")

    reject = sub.add_parser("reject", help="Record a rejected proposal in artifact metadata without applying")
    reject.add_argument("artifact", type=Path, help="Artifact directory")
    reject.add_argument("proposal", help="Proposal id to reject")
    reject.add_argument("--reason", help="Reason for the rejection (enforced in commands/review.py)")

    diff = sub.add_parser("diff", help="Show a staged artifact")
    diff.add_argument("artifact", type=Path, help="Artifact directory")
    diff.add_argument("--live-root", type=Path, default=None, help="Root of the live workspace")

    validate = sub.add_parser("validate", help="Validate a staged artifact")
    validate.add_argument("artifact", type=Path, help="Artifact directory")
    validate.add_argument("--live-root", type=Path, default=Path.cwd(), help="Root of the live workspace")

    apply = sub.add_parser("apply", help="Apply approved changes from an artifact")
    apply.add_argument("artifact", type=Path, help="Artifact directory")
    apply.add_argument("--live-root", type=Path, default=Path.cwd(), help="Root of the live workspace")
    apply.add_argument(
        "--backup-root",
        type=Path,
        default=Path.cwd() / ".dreaming" / "backups",
        help="Where backups are stored",
    )
    apply.add_argument("--approve", action="append", default=[], help="Compatibility shortcut: approve a proposal id or 'all' before applying")
    apply.add_argument("--dry-run", dest="dry_run", action="store_true", help="Preview what apply would do without writing to live state or creating backups")
    apply.add_argument(
        "--priority",
        default=None,
        help="Comma-separated priority values to include (low,normal,high)",
    )
    apply.add_argument(
        "--target-kind",
        dest="target_kind",
        default=None,
        help="Comma-separated target_kind values to include (memory,user,skill,fact)",
    )

    revert = sub.add_parser("revert", help="Restore an applied artifact's live files from the recorded backups")
    revert.add_argument("artifact", type=Path, help="Artifact directory")
    revert.add_argument("--live-root", type=Path, default=None, help="Root of the live workspace (defaults to artifact.workspace_root)")
    revert.add_argument("--backup-root", type=Path, default=None, help="Where backups are stored (defaults to <live-root>/.dreaming/backups)")
    revert.add_argument("--yes", dest="yes", action="store_true", help="Skip the confirmation prompt (required for non-interactive use)")

    discard = sub.add_parser("discard", help="Discard a staged artifact")
    discard.add_argument("artifact", type=Path, help="Artifact directory")
    discard.add_argument(
        "--archive-root",
        type=Path,
        default=Path.cwd() / ".dreaming" / "discarded",
        help="Where discarded artifacts are archived",
    )

    compact = sub.add_parser("compact", help="Archive terminal artifacts and keep the active root tidy")
    compact.add_argument(
        "--artifact-root",
        type=Path,
        default=Path.cwd() / ".dreaming" / "artifacts",
        help="Where artifacts are stored",
    )
    compact.add_argument(
        "--archive-root",
        type=Path,
        default=Path.cwd() / ".dreaming" / "archive",
        help="Where compacted artifacts are archived",
    )

    install_cron = sub.add_parser("install-cron", help="Register the nightly review-only cron job")
    install_cron.add_argument("--schedule", default=None, help="Cron schedule, defaults to nightly at 03:00 UTC")
    install_cron.add_argument("--mode", choices=["status-digest", "inbox-digest"], default="status-digest", help="Cron script mode")

    digest = sub.add_parser("digest", help="Render a local operator digest for an artifact or inbox")
    digest.add_argument("artifact", nargs="?", type=Path, help="Artifact directory")
    digest.add_argument("--artifact-root", type=Path, default=None, help="Root containing related artifact runs")
    digest.add_argument("--state-root", type=Path, default=None, help="State root containing runs.jsonl and DREAMS.md")
    digest.add_argument("--weekly", action="store_true", help="Include the weekly rollup section")
    digest.add_argument("--inbox", action="store_true", help="Render a queue-level digest instead of a single-artifact digest")
    digest.add_argument("--state", default=None, help="Comma-separated inbox states when --inbox is used")
    digest.add_argument("--priority", default=None, help="Comma-separated priorities when --inbox is used")
    digest.add_argument("--limit", type=int, default=20, help="Maximum inbox rows when --inbox is used")

    status = sub.add_parser("status", help="List known artifacts")
    status.add_argument("--artifact-root", type=Path, default=Path.cwd() / ".dreaming" / "artifacts", help="Where artifacts are stored")

    report_card = sub.add_parser("report-card", help="Render a redacted shareable artifact summary")
    report_card.add_argument("artifact", type=Path, help="Artifact directory")
    report_card.add_argument("--output", type=Path, default=None, help="Write the Markdown report card to a file")
    report_card.add_argument("--json", type=Path, default=None, help="Write a JSON companion to a file")

    update = sub.add_parser("update", help="Safely fast-forward the installed Hermes Dreaming checkout")
    update.add_argument("--remote", default="origin", help="Git remote to update from")
    update.add_argument("--branch", default="main", help="Branch to fast-forward onto")
    update.add_argument("--check", action="store_true", help="Report update status without pulling")
    update.add_argument("--no-verify", action="store_true", help="Skip the post-update pytest smoke")

    providers = sub.add_parser("providers", help="Discover available analysis providers")
    providers_sub = providers.add_subparsers(dest="providers_command", required=True)
    providers_sub.add_parser("list", help="List available providers and their status")

    return parser


def _record_cli_run(
    command: str,
    *,
    success: bool,
    artifact_id: str | None = None,
    artifact_status: str | None = None,
    artifact_dir: Path | None = None,
    artifact_root: Path | None = None,
    archive_root: Path | None = None,
    live_root: Path | None = None,
    summary: str | None = None,
    errors: list[str] | None = None,
) -> None:
    record: dict[str, object] = {
        "command": command,
        "success": success,
    }
    if artifact_id is not None:
        record["artifact_id"] = artifact_id
    if artifact_status is not None:
        record["artifact_status"] = artifact_status
    if artifact_dir is not None:
        record["artifact_dir"] = str(artifact_dir)
    if artifact_root is not None:
        record["artifact_root"] = str(artifact_root)
    if archive_root is not None:
        record["archive_root"] = str(archive_root)
    if live_root is not None:
        record["live_root"] = str(live_root)
    if summary is not None:
        record["summary"] = summary
    if errors:
        record["errors"] = list(errors)
    record_run(record)


def _parse_time_window(value: str) -> timedelta | None:
    """Parse a time-window string like '7d', '12h', '2w' into a timedelta."""
    text = (value or "").strip().lower()
    if not text:
        return None
    suffix = text[-1]
    if suffix not in {"h", "d", "w"}:
        raise ValueError(f"time window must end with h, d, or w (got {value!r})")
    try:
        number = int(text[:-1])
    except ValueError as exc:
        raise ValueError(f"time window must be a whole number followed by h, d, or w (got {value!r})") from exc
    if number <= 0:
        raise ValueError(f"time window must be greater than 0 (got {value!r})")
    if suffix == "h":
        return timedelta(hours=number)
    if suffix == "d":
        return timedelta(days=number)
    return timedelta(weeks=number)


def _resolve_creation_sources(args: argparse.Namespace, parser: argparse.ArgumentParser, *, command: str) -> list[Path]:
    sources = list(getattr(args, "source", None) or [])
    from_sessions = getattr(args, "from_sessions", None)
    recent = getattr(args, "recent", None)
    from_since = getattr(args, "from_since", None)
    harvest_count = from_sessions if from_sessions is not None else recent
    if harvest_count is not None or from_since is not None:
        if harvest_count is not None and harvest_count <= 0:
            parser.error(f"{command} --from-sessions/--recent must be greater than 0")
        if harvest_count is None:
            # --from-since without an explicit count: cap at 50
            harvest_count = 50
        if from_since is not None:
            try:
                window = _parse_time_window(from_since)
            except ValueError as exc:
                parser.error(str(exc))
            if window is not None:
                # Reduce count based on the time window: longer window => more sessions.
                # Cap at 50 per the spec.
                days = window.total_seconds() / 86400
                harvest_count = max(1, min(50, int(days * 4) or 1))
        harvest_out = getattr(args, "harvest_out", None)
        if harvest_out is None:
            harvest_out = Path(args.artifact_root) / "_sources" / "recent-sessions.md"
        result = harvest_recent(recent=harvest_count, output_path=harvest_out)
        print(f"harvest: {result.output_path}")
        print(f"sessions: {len(result.sessions)}")
        print(f"redactions: {result.redaction_count}")
        if result.output_path is not None:
            sources.append(result.output_path)
    if not sources:
        parser.error(f"{command} requires --source, --from-sessions, --from-since, or --recent")
    return sources


def _render_inbox_digest(result) -> str:
    high_priority = [row for row in result.rows if row.highest_priority == "high"]
    high_risk = [row for row in result.rows if row.highest_risk == "high"]
    lines = [
        "# Hermes Dreaming inbox digest",
        "",
        f"- Artifact root: `{result.artifact_root}`",
        f"- Active rows shown: `{len(result.rows)}`",
        f"- High-priority rows: `{len(high_priority)}`",
        f"- High-risk rows: `{len(high_risk)}`",
        "",
        "## Needs Tony",
        "",
    ]
    needs_tony = [row for row in result.rows if row.highest_priority == "high" or row.highest_risk == "high" or row.inbox_state in {"staged", "mixed", "approved"}]
    if needs_tony:
        for row in needs_tony[:10]:
            lines.append(f"- `{row.artifact_id}` [{row.inbox_state}] {row.highest_risk}/{row.highest_priority}: {row.top_reason}")
            lines.append(f"  - next: `{row.next_command}`")
    else:
        lines.append("- Nothing needs action.")
    safe = [row for row in result.rows if row not in needs_tony]
    lines.extend(["", "## Safe to ignore", ""])
    if safe:
        for row in safe[:10]:
            lines.append(f"- `{row.artifact_id}` [{row.inbox_state}] {row.top_reason}")
    else:
        lines.append("- none")
    lines.extend(["", "Transport: stdout only. Delivery belongs to the caller/cron wrapper."])
    return "\n".join(lines).rstrip() + "\n"


def _run_creation_like(command: str, args: argparse.Namespace, *, dry_run: bool, parser: argparse.ArgumentParser | None = None) -> int:
    source_paths = _resolve_creation_sources(args, parser or argparse.ArgumentParser(prog="dreaming"), command=command)
    provider_name = args.provider
    if getattr(args, "no_llm", False):
        provider_name = "offline-marker"
    result = (
        review_artifact(
            DreamRunConfig(
                live_root=args.live_root,
                artifact_root=args.artifact_root,
                source_paths=source_paths,
                provider_name=provider_name,
                model=args.model,
                api_key=args.api_key,
                base_url=args.base_url,
            )
        )
        if dry_run
        else create_dream_artifact(
            DreamRunConfig(
                live_root=args.live_root,
                artifact_root=args.artifact_root,
                source_paths=source_paths,
                provider_name=provider_name,
                model=args.model,
                api_key=args.api_key,
                base_url=args.base_url,
            )
        )
    )
    print(f"artifact: {result.artifact_dir}")
    print(f"status: {result.artifact.status}")
    print(f"proposals: {len(result.artifact.proposals)}")
    if dry_run:
        print("mode: dry-run")
    if result.validation_errors:
        print("validation: invalid")
        for error in result.validation_errors:
            print(f"- {error}")
        _record_cli_run(
            command,
            success=False,
            artifact_id=result.artifact.artifact_id,
            artifact_status=result.artifact.status,
            artifact_dir=result.artifact_dir,
            artifact_root=args.artifact_root,
            live_root=args.live_root,
            summary=("validation failed" if not dry_run else "dry-run validation failed"),
            errors=result.validation_errors,
        )
        return 1

    print("validation: valid")
    _record_cli_run(
        command,
        success=True,
        artifact_id=result.artifact.artifact_id,
        artifact_status=result.artifact.status,
        artifact_dir=result.artifact_dir,
        artifact_root=args.artifact_root,
        live_root=args.live_root,
        summary=(f"staged {len(result.artifact.proposals)} proposal(s)" if not dry_run else f"dry-run staged {len(result.artifact.proposals)} proposal(s)"),
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "create":
        return _run_creation_like("create", args, dry_run=False, parser=parser)

    if args.command == "harvest":
        result = harvest_recent(
            recent=args.recent,
            output_path=args.out,
            db_path=args.db_path,
            state_path=args.state_path,
            max_chars=args.max_chars,
        )
        print(f"harvest: {result.output_path}")
        print(f"sessions: {len(result.sessions)}")
        print(f"redactions: {result.redaction_count}")
        return 0

    if args.command == "inbox":
        result = build_inbox(
            args.artifact_root,
            state_filter=parse_filter(args.state),
            priority_filter=parse_filter(args.priority),
            apply_ready=getattr(args, "apply_ready", False),
            limit=args.limit,
        )
        print((render_inbox_json(result) if args.json else render_inbox(result)).rstrip())
        return 0

    if args.command == "review":
        if args.open_artifact is not None:
            artifact = load_artifact(args.open_artifact)
            output = render_open_brief(args.open_artifact)
            print(output.rstrip())
            _record_cli_run(
                "review",
                success=True,
                artifact_id=artifact.artifact_id,
                artifact_status=artifact.status,
                artifact_dir=args.open_artifact,
                live_root=Path(artifact.workspace_root),
                summary=f"opened artifact {artifact.artifact_id}",
            )
            return 0
        if not getattr(args, "source", None) and getattr(args, "recent", None) is None:
            parser.error("review requires --source or --recent unless --open is set")
        return _run_creation_like("review", args, dry_run=True, parser=parser)

    if args.command == "summarize":
        artifact = load_artifact(args.artifact)
        output = render_summary(args.artifact)
        print(output.rstrip())
        _record_cli_run(
            "summarize",
            success=True,
            artifact_id=artifact.artifact_id,
            artifact_status=artifact.status,
            artifact_dir=args.artifact,
            live_root=Path(artifact.workspace_root),
            summary=f"summarized artifact {artifact.artifact_id}",
        )
        return 0

    if args.command == "approve":
        try:
            result = approve_artifact(args.artifact, args.proposal)
        except ReviewError as exc:
            print(str(exc))
            _record_cli_run(
                "approve",
                success=False,
                artifact_dir=args.artifact,
                summary=str(exc),
            )
            return 1
        artifact = result.artifact
        if result.changed:
            print(f"approved artifact: {artifact.artifact_id} ({result.changed} changed)")
        else:
            print(f"approved artifact: {artifact.artifact_id} (no changes)")
        _record_cli_run(
            "approve",
            success=True,
            artifact_id=artifact.artifact_id,
            artifact_status=artifact.status,
            artifact_dir=args.artifact,
            live_root=Path(artifact.workspace_root),
            summary=f"approved {result.changed} proposal(s)",
        )
        return 0

    if args.command == "reject":
        try:
            result = reject_artifact(args.artifact, args.proposal, reason=args.reason)
        except ReviewError as exc:
            print(str(exc))
            _record_cli_run(
                "reject",
                success=False,
                artifact_dir=args.artifact,
                summary=str(exc),
            )
            return 1
        artifact = result.artifact
        if result.changed:
            print(f"rejected artifact: {artifact.artifact_id} ({result.changed} changed)")
        else:
            print(f"rejected artifact: {artifact.artifact_id} (no changes)")
        _record_cli_run(
            "reject",
            success=True,
            artifact_id=artifact.artifact_id,
            artifact_status=artifact.status,
            artifact_dir=args.artifact,
            live_root=Path(artifact.workspace_root),
            summary=f"rejected {result.changed} proposal(s)",
        )
        return 0

    if args.command == "diff":
        artifact = load_artifact(args.artifact)
        print(render_artifact_diff(artifact, live_root=args.live_root).rstrip())
        _record_cli_run(
            "diff",
            success=True,
            artifact_id=artifact.artifact_id,
            artifact_status=artifact.status,
            artifact_dir=args.artifact,
            live_root=args.live_root,
            summary=f"inspected artifact {artifact.artifact_id}",
        )
        return 0

    if args.command == "validate":
        artifact = load_artifact(args.artifact)
        errors = validate_artifact(artifact, live_root=args.live_root)
        if errors:
            print("artifact is invalid")
            for error in errors:
                print(f"- {error}")
            _record_cli_run(
                "validate",
                success=False,
                artifact_id=artifact.artifact_id,
                artifact_status=artifact.status,
                artifact_dir=args.artifact,
                live_root=args.live_root,
                summary="artifact is invalid",
                errors=errors,
            )
            return 1
        print("artifact is valid")
        _record_cli_run(
            "validate",
            success=True,
            artifact_id=artifact.artifact_id,
            artifact_status=artifact.status,
            artifact_dir=args.artifact,
            live_root=args.live_root,
            summary="artifact is valid",
        )
        return 0

    if args.command == "apply":
        approve_all = any(item.lower() in {"all", "*", "true", "yes"} for item in args.approve)
        approve_ids = [item for item in args.approve if item.lower() not in {"all", "*", "true", "yes"}]
        artifact = load_artifact(args.artifact)
        priority_filter = None
        target_kind_filter = None
        try:
            priority_filter = validate_priority_filter(parse_filter_list(getattr(args, "priority", None)))
            target_kind_filter = validate_target_kind_filter(parse_filter_list(getattr(args, "target_kind", None)))
        except DreamApplyError as exc:
            print(str(exc))
            _record_cli_run(
                "apply",
                success=False,
                artifact_id=artifact.artifact_id,
                artifact_status=artifact.status,
                artifact_dir=args.artifact,
                live_root=args.live_root,
                summary=str(exc),
            )
            return 1
        try:
            applied = apply_artifact(
                args.artifact,
                live_root=args.live_root,
                backup_root=args.backup_root,
                approve_all=approve_all,
                approve_ids=approve_ids,
                dry_run=args.dry_run,
                priority_filter=priority_filter,
                target_kind_filter=target_kind_filter,
            )
        except DreamApplyError as exc:
            print(str(exc))
            _record_cli_run(
                "apply",
                success=False,
                artifact_id=artifact.artifact_id,
                artifact_status=artifact.status,
                artifact_dir=args.artifact,
                live_root=args.live_root,
                summary=str(exc),
            )
            return 1
        if args.dry_run:
            report = getattr(applied, "dry_run_report", None)
            print("apply: dry-run")
            print(f"artifact: {applied.artifact_id}")
            print(f"would_apply_proposals: {len(report.would_apply_proposal_ids) if report else 0}")
            print(f"would_skip_proposals: {len(report.would_skip_proposal_ids) if report else 0}")
            print(f"would_backup_paths: {len(report.would_backup_paths) if report else 0}")
            print(f"would_write_targets: {len(report.would_write_targets) if report else 0}")
            if report and (report.filtered_out_priority or report.filtered_out_target_kind):
                print(f"filtered_out_priority: {', '.join(report.filtered_out_priority)}")
                print(f"filtered_out_target_kind: {', '.join(report.filtered_out_target_kind)}")
            print("no live writes performed")
            _record_cli_run(
                "apply",
                success=True,
                artifact_id=applied.artifact_id,
                artifact_status=applied.status,
                artifact_dir=args.artifact,
                live_root=args.live_root,
                summary="dry-run preview",
            )
            return 0
        print(f"applied artifact: {applied.artifact_id}")
        print(f"status: {applied.status}")
        _record_cli_run(
            "apply",
            success=True,
            artifact_id=applied.artifact_id,
            artifact_status=applied.status,
            artifact_dir=args.artifact,
            live_root=args.live_root,
            summary=f"applied artifact {applied.artifact_id}",
        )
        return 0

    if args.command == "revert":
        try:
            reverted = revert_artifact(
                args.artifact,
                live_root=args.live_root,
                backup_root=args.backup_root,
                yes=args.yes,
            )
        except DreamRevertError as exc:
            message = str(exc)
            print(message)
            # Confirmation prompt is the only path that raises without --yes
            # when the caller is interactive; treat it as a non-error and
            # exit 2 so callers can distinguish "needs confirmation" from
            # a real failure.
            if "Re-run with --yes to confirm" in message:
                return 2
            _record_cli_run(
                "revert",
                success=False,
                artifact_dir=args.artifact,
                summary=message.splitlines()[0] if message else "revert failed",
            )
            return 1
        print(f"reverted artifact: {reverted.artifact_id}")
        print(f"status: {reverted.status}")
        print(f"reverted_at: {reverted.reverted_at}")
        _record_cli_run(
            "revert",
            success=True,
            artifact_id=reverted.artifact_id,
            artifact_status=reverted.status,
            artifact_dir=args.artifact,
            summary=f"reverted artifact {reverted.artifact_id}",
        )
        return 0

    if args.command == "discard":
        artifact = load_artifact(args.artifact)
        archived = discard_artifact(args.artifact, archive_root=args.archive_root)
        print(f"discarded artifact: {archived}")
        _record_cli_run(
            "discard",
            success=True,
            artifact_id=artifact.artifact_id,
            artifact_status=artifact.status,
            artifact_dir=args.artifact,
            summary=f"discarded artifact {artifact.artifact_id}",
        )
        return 0

    if args.command == "compact":
        result = compact_artifacts(artifact_root=args.artifact_root, archive_root=args.archive_root)
        print(f"artifact root: {result.artifact_root}")
        print(f"archive root: {result.archive_root}")
        print(f"moved: {len(result.moved)}")
        if result.moved:
            for artifact_id, status in result.moved:
                print(f"- archived {artifact_id} ({status})")
        else:
            print("- no terminal artifacts to compact")
        print(f"kept: {len(result.kept)}")
        _record_cli_run(
            "compact",
            success=True,
            artifact_root=args.artifact_root,
            archive_root=args.archive_root,
            summary=f"archived {len(result.moved)} terminal artifact(s)",
        )
        return 0

    if args.command == "install-cron":
        message = install_cron_command(schedule=args.schedule, mode=args.mode)
        print(message.rstrip())
        _record_cli_run(
            "install-cron",
            success="error" not in message.lower(),
            summary=message.splitlines()[0] if message else "install-cron completed",
        )
        return 0 if "error" not in message.lower() else 1

    if args.command == "digest":
        if args.inbox:
            artifact_root = args.artifact_root or (Path.cwd() / ".dreaming" / "artifacts")
            inbox_digest = build_inbox_digest(
                artifact_root,
                state_filter=parse_filter(args.state),
                priority_filter=parse_filter(args.priority),
                limit=args.limit,
            )
            print(render_inbox_digest(inbox_digest).rstrip())
            _record_cli_run(
                "digest",
                success=True,
                artifact_root=artifact_root,
                summary=f"rendered inbox digest with {inbox_digest.active_artifacts} active artifact(s)",
            )
            return 0
        if args.artifact is None:
            parser.error("digest requires an artifact unless --inbox is set")
        digest = build_digest(
            args.artifact,
            artifact_root=args.artifact_root,
            state_root=args.state_root,
            include_weekly=args.weekly,
        )
        print(render_digest(digest).rstrip())
        _record_cli_run(
            "digest",
            success=True,
            artifact_id=digest.artifact.artifact_id,
            artifact_status=digest.artifact.status,
            artifact_dir=args.artifact,
            artifact_root=args.artifact_root,
            live_root=Path(digest.artifact.workspace_root),
            summary=f"rendered digest for {digest.artifact.artifact_id}",
        )
        return 0

    if args.command == "status":
        snapshot = build_status_snapshot(artifact_root=args.artifact_root)
        print(render_status(snapshot).rstrip())
        return 0

    if args.command == "report-card":
        report_card = report_card_command(args.artifact)
        markdown = render_report_card_markdown(report_card)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(markdown, encoding="utf-8")
        else:
            print(markdown.rstrip())
        if args.json is not None:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(render_report_card_json(report_card), encoding="utf-8")
        _record_cli_run(
            "report-card",
            success=True,
            artifact_id=report_card.artifact_id,
            artifact_status=report_card.status,
            artifact_dir=args.artifact,
            summary=f"rendered redacted report card for {report_card.artifact_id}",
        )
        return 0

    if args.command == "update":
        repo_root = _discover_update_repo_root()
        result = update_command(
            repo_root=repo_root,
            remote=args.remote,
            branch=args.branch,
            check=args.check,
            verify=not args.no_verify,
        )
        print(render_update_result(result).rstrip())
        _record_cli_run(
            "update",
            success=result.success,
            summary=result.message.splitlines()[0] if result.message else "update completed",
            errors=[result.message] if not result.success and result.message else None,
        )
        return 0 if result.success else 1

    if args.command == "providers":
        if args.providers_command == "list":
            rows = list_providers()
            print(render_providers_table(rows).rstrip())
            return 0
        parser.error(f"unknown providers subcommand: {args.providers_command}")
        return 2

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
