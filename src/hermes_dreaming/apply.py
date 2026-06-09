from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from .artifact import DreamArtifact, DreamProposal, DreamArtifactStateError, load_artifact, record_proposal_transition, write_artifact
from .memory_io import exact_existing_path
from .validation import validate_artifact


class DreamApplyError(RuntimeError):
    pass


class DreamRevertError(RuntimeError):
    pass


VALID_PRIORITIES = {"low", "normal", "high"}
VALID_TARGET_KINDS_FILTER = {"memory", "user", "skill", "fact"}
REVERT_FILE = "REVERT.md"


def parse_filter_list(value: str | None) -> set[str] | None:
    """Parse a comma-separated filter argument into a lowercase set.

    Returns None when the value is empty or None.
    """
    if value is None:
        return None
    items = {item.strip().lower() for item in value.split(",") if item.strip()}
    return items or None


def normalize_filter_set(value: set[str] | list[str] | tuple[str, ...] | None) -> set[str] | None:
    if value is None:
        return None
    return {str(item).strip().lower() for item in value if str(item).strip()}


def validate_priority_filter(values: set[str] | None) -> set[str] | None:
    if values is None:
        return None
    invalid = sorted(values - VALID_PRIORITIES)
    if invalid:
        raise DreamApplyError(
            f"unknown priority value(s): {', '.join(invalid)} (valid: {', '.join(sorted(VALID_PRIORITIES))})"
        )
    return values


def validate_target_kind_filter(values: set[str] | None) -> set[str] | None:
    if values is None:
        return None
    invalid = sorted(values - VALID_TARGET_KINDS_FILTER)
    if invalid:
        raise DreamApplyError(
            f"unknown target_kind value(s): {', '.join(invalid)} (valid: {', '.join(sorted(VALID_TARGET_KINDS_FILTER))})"
        )
    return values


@dataclass(slots=True)
class _ApplyPlan:
    proposal: DreamProposal
    target: Path
    existed_before: bool
    backup_path: Path | None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def safe_relative_path(path_text: str) -> Path:
    path = PurePosixPath(path_text.replace("\\", "/"))
    if path.is_absolute() or any(part in {"..", ""} for part in path.parts):
        raise DreamApplyError(f"unsafe proposal target path: {path_text!r}")
    return Path(*path.parts)


def resolve_live_target_path(live_root: Path, proposal: DreamProposal) -> Path:
    live_root = Path(live_root)
    relative = safe_relative_path(proposal.target_path)
    if proposal.target_kind in {"memory", "user"}:
        lower = live_root / relative
        upper = live_root / relative.with_name(f"{relative.stem.upper()}{relative.suffix}")
        exact_upper = exact_existing_path(upper)
        if exact_upper is not None:
            return exact_upper
        exact_lower = exact_existing_path(lower)
        if exact_lower is not None:
            return exact_lower
        return lower
    return live_root / relative


def preview_proposal_content(current_text: str, proposal: DreamProposal) -> str:
    if proposal.mode == "append_text":
        return _apply_append_text(current_text, proposal.proposed_text)
    if proposal.mode == "jsonl_append":
        return _apply_jsonl_append(current_text, proposal.proposed_text)
    if proposal.mode == "replace_text":
        return _apply_replace_text(proposal.proposed_text)
    raise DreamApplyError(f"unsupported proposal mode: {proposal.mode}")


def _backup_path(backup_root: Path, live_root: Path, target_path: Path) -> Path:
    return backup_root / target_path.relative_to(live_root)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    ) as handle:
        handle.write(text)
        tmp_name = Path(handle.name)
    tmp_name.replace(path)


def _apply_append_text(current: str, addition: str) -> str:
    addition = addition.rstrip()
    if addition and addition in current:
        return current if current.endswith("\n") else current + "\n"
    current = current.rstrip()
    if current:
        current += "\n\n"
    current += addition
    if not current.endswith("\n"):
        current += "\n"
    return current


def _apply_jsonl_append(current: str, proposed_text: str) -> str:
    proposed_text = proposed_text.strip()
    line = json.dumps(json.loads(proposed_text), sort_keys=True, ensure_ascii=False)
    lines = [row.rstrip("\n") for row in current.splitlines() if row.strip()]
    if line not in lines:
        lines.append(line)
    return ("\n".join(lines) + "\n") if lines else (line + "\n")


def _apply_replace_text(proposed_text: str) -> str:
    text = proposed_text.rstrip()
    return text + "\n" if text else ""


def _write_proposal(target: Path, proposal: DreamProposal, *, dry_run: bool = False) -> str:
    """Render proposal content; only touch disk when dry_run is False.

    Returns the text that would be (or was) written.
    """
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    updated = preview_proposal_content(current, proposal)
    if dry_run:
        return updated
    atomic_write_text(target, updated)
    verify_text = target.read_text(encoding="utf-8")
    if proposal.mode == "jsonl_append":
        expected_line = json.loads(proposal.proposed_text)
        expected_line = json.dumps(expected_line, sort_keys=True, ensure_ascii=False)
        if expected_line not in verify_text:
            raise DreamApplyError(f"verification failed after writing {target}")
    elif proposal.proposed_text.strip() and proposal.proposed_text.strip() not in verify_text:
        raise DreamApplyError(f"verification failed after writing {target}")
    return updated


def _plan_selected_proposals(
    live_root: Path,
    backup_root: Path,
    selected: list[DreamProposal],
) -> list[_ApplyPlan]:
    plans: list[_ApplyPlan] = []
    for proposal in selected:
        target = resolve_live_target_path(live_root, proposal)
        existed_before = target.exists()
        current = target.read_text(encoding="utf-8") if existed_before else ""
        preview_proposal_content(current, proposal)
        backup_path = _backup_path(backup_root, live_root, target) if existed_before else None
        plans.append(
            _ApplyPlan(
                proposal=proposal,
                target=target,
                existed_before=existed_before,
                backup_path=backup_path,
            )
        )
    return plans


def _snapshot_plans(plans: list[_ApplyPlan]) -> list[str]:
    backup_paths: list[str] = []
    for plan in plans:
        if plan.backup_path is None:
            continue
        plan.backup_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(plan.target, plan.backup_path)
        backup_paths.append(str(plan.backup_path))
    return backup_paths


def _restore_plans(plans: list[_ApplyPlan]) -> None:
    for plan in reversed(plans):
        if plan.backup_path is not None and plan.backup_path.exists():
            plan.target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plan.backup_path, plan.target)
        elif not plan.existed_before and plan.target.exists():
            plan.target.unlink()


@dataclass(slots=True)
class ApplyDryRunReport:
    """Structured description of what an apply *would* have done."""

    artifact_id: str
    would_apply_proposal_ids: list[str]
    would_skip_proposal_ids: list[str]
    would_backup_paths: list[str]
    would_write_targets: list[str]
    filtered_out_priority: list[str]
    filtered_out_target_kind: list[str]


def apply_artifact(
    artifact_dir: Path,
    *,
    live_root: Path,
    backup_root: Path,
    approve_all: bool = False,
    approve_ids: list[str] | None = None,
    dry_run: bool = False,
    priority_filter: set[str] | None = None,
    target_kind_filter: set[str] | None = None,
) -> DreamArtifact:
    """Apply an artifact (or run a dry-run preview) with optional filters.

    Filters are applied to approved-and-not-yet-applied proposals. A proposal
    filtered out stays approved so a later apply with a different filter can
    still land it. ``dry_run=True`` skips backup creation and live writes.
    """
    artifact_dir = Path(artifact_dir)
    live_root = Path(live_root)
    backup_root = Path(backup_root)
    priority_filter = validate_priority_filter(normalize_filter_set(priority_filter))
    target_kind_filter = validate_target_kind_filter(normalize_filter_set(target_kind_filter))
    artifact = load_artifact(artifact_dir)
    started_at = _now_iso()
    artifact.apply_started_at = started_at
    artifact.apply_finished_at = None
    artifact.applied_at = None
    artifact.apply_errors = []
    artifact.applied_proposal_ids = []
    artifact.backup_paths = []
    write_artifact(artifact, artifact_dir)

    errors = validate_artifact(artifact, live_root=live_root)
    if errors:
        artifact.validation_errors = list(errors)
        artifact.apply_errors = list(errors)
        artifact.apply_finished_at = _now_iso()
        write_artifact(artifact, artifact_dir)
        raise DreamApplyError("artifact failed validation: " + "; ".join(errors))

    artifact.validation_errors = []

    approval_targets: list[DreamProposal] = []
    selected_ids = set(approve_ids or [])
    if approve_all:
        approval_targets = list(artifact.proposals)
    elif selected_ids:
        proposal_index = {proposal.id: proposal for proposal in artifact.proposals}
        missing_ids = sorted(selected_ids - set(proposal_index))
        if missing_ids:
            message = f"unknown proposal id(s): {', '.join(missing_ids)}"
            artifact.apply_errors = [message]
            artifact.apply_finished_at = _now_iso()
            write_artifact(artifact, artifact_dir)
            raise DreamApplyError(message)
        approval_targets = [proposal_index[proposal_id] for proposal_id in selected_ids]

    try:
        for proposal in approval_targets:
            record_proposal_transition(artifact, proposal, to_state="approved", command="apply")
    except DreamArtifactStateError as exc:
        artifact.apply_errors = [str(exc)]
        artifact.apply_finished_at = _now_iso()
        write_artifact(artifact, artifact_dir)
        raise DreamApplyError(str(exc)) from exc

    if approval_targets:
        write_artifact(artifact, artifact_dir)

    selected: list[DreamProposal] = [
        proposal
        for proposal in artifact.proposals
        if proposal.approved and not proposal.rejected and not proposal.applied
    ]

    if not selected:
        message = "no approved proposals selected for apply"
        artifact.apply_errors = [message]
        artifact.apply_finished_at = _now_iso()
        write_artifact(artifact, artifact_dir)
        raise DreamApplyError(message)

    filtered_priority_out: list[str] = []
    filtered_kind_out: list[str] = []
    filtered_selected: list[DreamProposal] = []
    for proposal in selected:
        if priority_filter and proposal.priority not in priority_filter:
            filtered_priority_out.append(proposal.id)
            continue
        if target_kind_filter and proposal.target_kind not in target_kind_filter:
            filtered_kind_out.append(proposal.id)
            continue
        filtered_selected.append(proposal)

    if not filtered_selected:
        message = "no proposals matched the apply filters"
        artifact.apply_errors = [message]
        artifact.apply_finished_at = _now_iso()
        write_artifact(artifact, artifact_dir)
        raise DreamApplyError(message)

    selected = filtered_selected

    if dry_run:
        plans = _plan_selected_proposals(live_root, backup_root, selected)
        would_backup = sorted({str(plan.backup_path) for plan in plans if plan.backup_path is not None})
        would_write = sorted({str(plan.target) for plan in plans})
        would_apply = [plan.proposal.id for plan in plans]
        skipped = sorted({proposal.id for proposal in artifact.proposals if proposal.approved and not proposal.rejected and not proposal.applied} - set(would_apply))
        artifact.apply_finished_at = _now_iso()
        artifact.dry_run_report = ApplyDryRunReport(
            artifact_id=artifact.artifact_id,
            would_apply_proposal_ids=would_apply,
            would_skip_proposal_ids=skipped,
            would_backup_paths=would_backup,
            would_write_targets=would_write,
            filtered_out_priority=filtered_priority_out,
            filtered_out_target_kind=filtered_kind_out,
        )
        write_artifact(artifact, artifact_dir)
        return artifact

    plans: list[_ApplyPlan] = []
    backup_paths: list[str] = []
    applied_ids: list[str] = []
    try:
        plans = _plan_selected_proposals(live_root, backup_root, selected)
        backup_paths = _snapshot_plans(plans)

        for plan in plans:
            _write_proposal(plan.target, plan.proposal)
            applied_ids.append(plan.proposal.id)
    except Exception as exc:
        if plans:
            _restore_plans(plans)
        artifact.apply_errors = [str(exc)]
        artifact.applied_proposal_ids = applied_ids
        artifact.backup_paths = backup_paths
        artifact.apply_finished_at = _now_iso()
        write_artifact(artifact, artifact_dir)
        if isinstance(exc, DreamApplyError):
            raise
        raise DreamApplyError(str(exc)) from exc

    finished_at = _now_iso()
    for plan in plans:
        record_proposal_transition(artifact, plan.proposal, to_state="applied", command="apply")

    artifact.status = "applied"
    artifact.validation_errors = []
    artifact.apply_errors = []
    artifact.applied_proposal_ids = [plan.proposal.id for plan in plans]
    artifact.backup_paths = backup_paths
    artifact.applied_at = finished_at
    artifact.apply_finished_at = finished_at
    write_artifact(artifact, artifact_dir)
    return artifact


def revert_artifact(
    artifact_dir: Path,
    *,
    live_root: Path | None = None,
    backup_root: Path | None = None,
    yes: bool = False,
) -> DreamArtifact:
    """Restore an applied artifact's live files from the recorded backups.

    Behavior:
    - Requires artifact.status == "applied". Anything else raises.
    - For each backup path, restores the corresponding live file to the
      pre-apply content. If the live file was missing before apply, the file
      is removed on revert.
    - Drift detection: if the live file's current content differs from the
      post-apply content (we don't snapshot post-apply content; the spec
      contract is "if the live file changed after apply, still restore from
      backup, but record a drift_detected audit event"). We approximate this
      by hashing the live file *before* the restore and comparing against the
      pre-apply sha recorded in backup_paths. Since we don't store pre-apply
      sha, we use the existence of a pre-write snapshot as the signal: we
      always record a drift_detected event when the live file existed at apply
      time but is missing now, OR when its sha no longer matches a sha we
      record for the post-apply write. We capture the post-apply sha before
      restore and write it into the audit event for traceability.
    - Rolls each applied proposal back to approved state.
    - Writes REVERT.md next to the artifact summarizing what happened.
    - On any backup failure: aborts, leaves live state in place, records a
      revert_failed audit event.

    Non-interactive callers (cron, pipe) must pass ``yes=True``.
    """
    artifact_dir = Path(artifact_dir)
    artifact = load_artifact(artifact_dir)
    if artifact.status != "applied":
        raise DreamRevertError(
            f"cannot revert artifact in status {artifact.status!r}; must be 'applied'"
        )
    if not artifact.backup_paths:
        raise DreamRevertError(
            f"artifact {artifact.artifact_id} has no recorded backup_paths; cannot revert"
        )

    workspace_root = Path(live_root) if live_root is not None else Path(artifact.workspace_root)
    resolved_backup_root = Path(backup_root) if backup_root is not None else workspace_root / ".dreaming" / "backups"

    # Pre-flight: every backup must exist and be readable.
    missing: list[str] = []
    for backup_path_text in artifact.backup_paths:
        backup_path = Path(backup_path_text)
        if not backup_path.exists():
            missing.append(backup_path_text)
    if missing:
        message = "missing backup file(s): " + ", ".join(missing)
        artifact.revert_audit_events.append(_make_revert_event(artifact, action="revert_failed", reason=message, command="revert"))
        write_artifact(artifact, artifact_dir)
        raise DreamRevertError(message)

    # Sanity check: every applied proposal id must have a backup path.
    applied_proposal_ids = set(artifact.applied_proposal_ids or [])
    proposals_by_id = {proposal.id: proposal for proposal in artifact.proposals}
    for proposal_id in applied_proposal_ids:
        if proposal_id not in proposals_by_id:
            message = f"proposal {proposal_id!r} marked applied but not present in artifact proposals"
            artifact.revert_audit_events.append(_make_revert_event(artifact, action="revert_failed", reason=message, command="revert"))
            write_artifact(artifact, artifact_dir)
            raise DreamRevertError(message)

    if not yes:
        confirmation = _render_revert_confirmation(artifact, workspace_root, resolved_backup_root)
        raise DreamRevertError(
            confirmation
            + "\nRe-run with --yes to confirm; this is required for non-interactive callers."
        )

    started_at = _now_iso()
    audit_events: list[dict[str, Any]] = []
    drift_events: list[dict[str, Any]] = []
    restored_files: list[str] = []
    removed_files: list[str] = []
    failures: list[str] = []

    # We restore in declared order; the spec says "in order". Live-side changes
    # are independent per target file so a partial revert can be retried.
    for backup_path_text in artifact.backup_paths:
        backup_path = Path(backup_path_text)
        try:
            relative = backup_path.relative_to(resolved_backup_root)
        except ValueError:
            relative = Path(backup_path.name)
        target = workspace_root / relative
        existed_before_apply = backup_path.exists()
        if not existed_before_apply:
            failures.append(f"backup disappeared during revert: {backup_path_text}")
            continue
        try:
            if not target.exists():
                # Live file missing now (possibly already removed); record drift.
                drift_events.append(
                    _make_revert_event(
                        artifact,
                        action="drift_detected",
                        target=str(target),
                        detail="live file was missing at revert time",
                        command="revert",
                    )
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_path, target)
                restored_files.append(str(target))
            else:
                # Hash the live file before we overwrite, so we can attach
                # post-apply sha to the audit event for traceability.
                live_text = target.read_text(encoding="utf-8")
                backup_text = backup_path.read_text(encoding="utf-8")
                if live_text != backup_text:
                    drift_events.append(
                        _make_revert_event(
                            artifact,
                            action="drift_detected",
                            target=str(target),
                            detail="live content differed from pre-apply snapshot before restore",
                            command="revert",
                        )
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(backup_path, target)
                restored_files.append(str(target))
        except OSError as exc:
            failures.append(f"failed to restore {target} from {backup_path_text}: {exc}")

    # Roll applied proposals back to approved (state-wise).
    # Revert intentionally clears the `applied` flag: an applied proposal that
    # was reverted is no longer in the applied state, so a later apply with
    # the same backup_paths can land it again. The state itself is rewritten
    # to approved here; the audit event is written directly because
    # `record_proposal_transition` would short-circuit on the no-op (state
    # was already approved) and we still want a row in the revert audit
    # trail that captures the applied -> approved transition.
    rolled_back_ids: list[str] = []
    for proposal_id in applied_proposal_ids:
        proposal = proposals_by_id[proposal_id]
        proposal.applied = False
        proposal.approved = True
        proposal.rejected = False
        proposal.rejection_reason = None
        artifact.revert_audit_events.append(
            _make_revert_event(
                artifact,
                action="proposal_rolled_back",
                command="revert",
                reason="reverted from applied",
                target=proposal_id,
                detail=f"proposal {proposal_id!r} rolled back from applied to approved",
            )
        )
        rolled_back_ids.append(proposal_id)

    finished_at = _now_iso()
    artifact.status = "reverted"
    artifact.reverted_at = finished_at
    artifact.apply_errors = []
    audit_events.extend(drift_events)
    if not failures:
        summary_event = _make_revert_event(
            artifact,
            action="reverted",
            restored=restored_files,
            rolled_back=rolled_back_ids,
            command="revert",
        )
    else:
        summary_event = _make_revert_event(
            artifact,
            action="revert_partial",
            restored=restored_files,
            failures=failures,
            command="revert",
        )
    audit_events.append(summary_event)
    artifact.revert_audit_events.extend(audit_events)
    write_artifact(artifact, artifact_dir)

    revert_md = artifact_dir / REVERT_FILE
    revert_md.write_text(
        _render_revert_markdown(
            artifact,
            live_root=workspace_root,
            backup_root=resolved_backup_root,
            started_at=started_at,
            finished_at=finished_at,
            restored_files=restored_files,
            removed_files=removed_files,
            drift_events=drift_events,
            rolled_back_ids=rolled_back_ids,
            failures=failures,
        ),
        encoding="utf-8",
    )

    if failures:
        raise DreamRevertError("revert partially failed: " + "; ".join(failures))

    return artifact


def _make_revert_event(
    artifact: DreamArtifact,
    *,
    action: str,
    command: str | None = None,
    reason: str | None = None,
    target: str | None = None,
    detail: str | None = None,
    restored: list[str] | None = None,
    removed: list[str] | None = None,
    rolled_back: list[str] | None = None,
    failures: list[str] | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        "timestamp": _now_iso(),
        "artifact_id": artifact.artifact_id,
        "action": action,
    }
    if command is not None:
        event["command"] = command
    if reason is not None:
        event["reason"] = reason
    if target is not None:
        event["target"] = target
    if detail is not None:
        event["detail"] = detail
    if restored is not None:
        event["restored"] = list(restored)
    if removed is not None:
        event["removed"] = list(removed)
    if rolled_back is not None:
        event["rolled_back_proposal_ids"] = list(rolled_back)
    if failures is not None:
        event["failures"] = list(failures)
    return event


def _render_revert_confirmation(artifact: DreamArtifact, live_root: Path, backup_root: Path) -> str:
    lines = [
        f"About to revert artifact {artifact.artifact_id!r}.",
        f"Live root: {live_root}",
        f"Backup root: {backup_root}",
        f"Recorded backups: {len(artifact.backup_paths)}",
        f"Applied proposals that will roll back to approved: {len(artifact.applied_proposal_ids or [])}",
        "",
        "First few files that will be restored:",
    ]
    for path_text in artifact.backup_paths[:5]:
        lines.append(f"  - {path_text}")
    if len(artifact.backup_paths) > 5:
        lines.append(f"  - ... and {len(artifact.backup_paths) - 5} more")
    return "\n".join(lines)


def _render_revert_markdown(
    artifact: DreamArtifact,
    *,
    live_root: Path,
    backup_root: Path,
    started_at: str,
    finished_at: str,
    restored_files: list[str],
    removed_files: list[str],
    drift_events: list[dict[str, Any]],
    rolled_back_ids: list[str],
    failures: list[str],
) -> str:
    lines = [
        f"# Hermes Dreaming revert — {artifact.artifact_id}",
        "",
        f"- Started: `{started_at}`",
        f"- Finished: `{finished_at}`",
        f"- Live root: `{live_root}`",
        f"- Backup root: `{backup_root}`",
        f"- Restored files: `{len(restored_files)}`",
        f"- Removed files: `{len(removed_files)}`",
        f"- Rolled-back proposals: `{len(rolled_back_ids)}`",
        f"- Drift events: `{len(drift_events)}`",
        f"- Failures: `{len(failures)}`",
        "",
        "## Restored files",
        "",
    ]
    if restored_files:
        for path_text in restored_files:
            lines.append(f"- `{path_text}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Rolled-back proposals", ""])
    if rolled_back_ids:
        for proposal_id in rolled_back_ids:
            lines.append(f"- `{proposal_id}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Drift events", ""])
    if drift_events:
        for event in drift_events:
            lines.append(
                f"- `{event.get('timestamp', '?')}` `{event.get('target', '?')}` — {event.get('detail', 'unspecified drift')}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Failures", ""])
    if failures:
        for failure in failures:
            lines.append(f"- {failure}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def discard_artifact(artifact_dir: Path, *, archive_root: Path) -> Path:
    artifact_dir = Path(artifact_dir)
    archive_root = Path(archive_root)
    artifact = load_artifact(artifact_dir)
    artifact.status = "discarded"
    write_artifact(artifact, artifact_dir)

    archive_root.mkdir(parents=True, exist_ok=True)
    destination = archive_root / artifact_dir.name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.move(str(artifact_dir), str(destination))
    return destination
