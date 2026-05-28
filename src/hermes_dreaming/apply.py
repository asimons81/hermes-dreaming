from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .artifact import DreamArtifact, DreamProposal, load_artifact, write_artifact
from .validation import validate_artifact


class DreamApplyError(RuntimeError):
    pass


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
    return Path(live_root) / safe_relative_path(proposal.target_path)


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


def _write_proposal(target: Path, proposal: DreamProposal) -> None:
    current = target.read_text(encoding="utf-8") if target.exists() else ""
    updated = preview_proposal_content(current, proposal)

    atomic_write_text(target, updated)

    verify_text = target.read_text(encoding="utf-8")
    if proposal.mode == "jsonl_append":
        expected_line = json.dumps(json.loads(proposal.proposed_text), sort_keys=True, ensure_ascii=False)
        if expected_line not in verify_text:
            raise DreamApplyError(f"verification failed after writing {target}")
    elif proposal.proposed_text.strip() and proposal.proposed_text.strip() not in verify_text:
        raise DreamApplyError(f"verification failed after writing {target}")


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


def apply_artifact(
    artifact_dir: Path,
    *,
    live_root: Path,
    backup_root: Path,
    approve_all: bool = False,
    approve_ids: list[str] | None = None,
) -> DreamArtifact:
    artifact_dir = Path(artifact_dir)
    live_root = Path(live_root)
    backup_root = Path(backup_root)
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

    selected_ids = set(approve_ids or [])
    selected: list[DreamProposal] = []
    for proposal in artifact.proposals:
        approved = approve_all or proposal.approved or proposal.id in selected_ids
        if approved:
            selected.append(proposal)

    if not selected:
        message = "no approved proposals selected for apply"
        artifact.apply_errors = [message]
        artifact.apply_finished_at = _now_iso()
        write_artifact(artifact, artifact_dir)
        raise DreamApplyError(message)

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
        plan.proposal.applied = True

    artifact.status = "applied"
    artifact.validation_errors = []
    artifact.apply_errors = []
    artifact.applied_proposal_ids = [plan.proposal.id for plan in plans]
    artifact.backup_paths = backup_paths
    artifact.applied_at = finished_at
    artifact.apply_finished_at = finished_at
    write_artifact(artifact, artifact_dir)
    return artifact


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
