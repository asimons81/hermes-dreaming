from __future__ import annotations

import json
import shutil
from pathlib import Path, PurePosixPath
import tempfile

from .artifact import DreamArtifact, DreamProposal, load_artifact, write_artifact
from .validation import validate_artifact


class DreamApplyError(RuntimeError):
    pass


def _safe_relative_path(path_text: str) -> Path:
    path = PurePosixPath(path_text.replace("\\", "/"))
    if path.is_absolute() or any(part in {"..", ""} for part in path.parts):
        raise DreamApplyError(f"unsafe proposal target path: {path_text!r}")
    return Path(*path.parts)


def _resolve_live_path(live_root: Path, proposal: DreamProposal) -> Path:
    return live_root / _safe_relative_path(proposal.target_path)


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
    if proposal.mode == "append_text":
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        updated = _apply_append_text(current, proposal.proposed_text)
    elif proposal.mode == "jsonl_append":
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        updated = _apply_jsonl_append(current, proposal.proposed_text)
    elif proposal.mode == "replace_text":
        updated = _apply_replace_text(proposal.proposed_text)
    else:  # pragma: no cover - guarded by validation
        raise DreamApplyError(f"unsupported proposal mode: {proposal.mode}")

    atomic_write_text(target, updated)

    verify_text = target.read_text(encoding="utf-8")
    if proposal.mode == "jsonl_append":
        expected_line = json.dumps(json.loads(proposal.proposed_text), sort_keys=True, ensure_ascii=False)
        if expected_line not in verify_text:
            raise DreamApplyError(f"verification failed after writing {target}")
    elif proposal.proposed_text.strip() and proposal.proposed_text.strip() not in verify_text:
        raise DreamApplyError(f"verification failed after writing {target}")


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

    errors = validate_artifact(artifact, live_root=live_root)
    if errors:
        raise DreamApplyError("artifact failed validation: " + "; ".join(errors))

    selected_ids = set(approve_ids or [])
    selected: list[DreamProposal] = []
    for proposal in artifact.proposals:
        approved = approve_all or proposal.approved or proposal.id in selected_ids
        if approved:
            selected.append(proposal)

    if not selected:
        raise DreamApplyError("no approved proposals selected for apply")

    for proposal in selected:
        target = _resolve_live_path(live_root, proposal)
        if target.exists():
            backup = _backup_path(backup_root, live_root, target)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        _write_proposal(target, proposal)
        proposal.applied = True

    artifact.status = "applied"
    artifact.validation_errors = []
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
