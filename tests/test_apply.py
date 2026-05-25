from __future__ import annotations

from pathlib import Path

import pytest

from hermes_dreaming.artifact import DreamArtifact, DreamProposal, load_artifact, write_artifact
from hermes_dreaming.apply import apply_artifact, discard_artifact, DreamApplyError


def _artifact(tmp_path: Path, proposal: DreamProposal) -> tuple[Path, DreamArtifact]:
    artifact = DreamArtifact(
        artifact_id="artifact-apply",
        created_at="2026-05-25T12:00:00Z",
        provider="offline-marker",
        status="validated",
        workspace_root=str(tmp_path),
        source_roots=[str(tmp_path / "sources")],
        report="# Report",
        sources=[],
        proposals=[proposal],
    )
    artifact_dir = tmp_path / "artifact"
    write_artifact(artifact, artifact_dir)
    return artifact_dir, artifact


def test_apply_appends_memory_and_writes_backup(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    memory = live_root / "memory.md"
    memory.write_text("# MEMORY\n\n- Existing note\n", encoding="utf-8")

    proposal = DreamProposal(
        id="proposal-memory",
        target_kind="memory",
        target_path="memory.md",
        mode="append_text",
        summary="append memory note",
        provenance=["sessions/1.md:1"],
        proposed_text="- Keep updates short and concrete.",
        approved=True,
    )
    artifact_dir, artifact = _artifact(tmp_path, proposal)
    backup_root = tmp_path / "backups"

    result = apply_artifact(artifact_dir, live_root=live_root, backup_root=backup_root, approve_all=True)

    assert result.status == "applied"
    assert memory.read_text(encoding="utf-8").strip().endswith("- Keep updates short and concrete.")
    assert (backup_root / "memory.md").exists()
    assert load_artifact(artifact_dir).status == "applied"


def test_apply_requires_approval(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    (live_root / "memory.md").write_text("# MEMORY\n", encoding="utf-8")

    proposal = DreamProposal(
        id="proposal-memory",
        target_kind="memory",
        target_path="memory.md",
        mode="append_text",
        summary="append memory note",
        provenance=["sessions/1.md:1"],
        proposed_text="- Keep updates short and concrete.",
        approved=False,
    )
    artifact_dir, _artifact_result = _artifact(tmp_path, proposal)

    with pytest.raises(DreamApplyError):
        apply_artifact(artifact_dir, live_root=live_root, backup_root=tmp_path / "backups", approve_all=False)


def test_discard_moves_artifact_to_archive_without_live_mutation(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    memory = live_root / "memory.md"
    memory.write_text("# MEMORY\n", encoding="utf-8")

    proposal = DreamProposal(
        id="proposal-memory",
        target_kind="memory",
        target_path="memory.md",
        mode="append_text",
        summary="append memory note",
        provenance=["sessions/1.md:1"],
        proposed_text="- Keep updates short and concrete.",
        approved=True,
    )
    artifact_dir, artifact = _artifact(tmp_path, proposal)
    archive_root = tmp_path / "archive"

    discarded_path = discard_artifact(artifact_dir, archive_root=archive_root)

    assert discarded_path.exists()
    assert not artifact_dir.exists()
    assert memory.read_text(encoding="utf-8") == "# MEMORY\n"
    assert load_artifact(discarded_path).status == "discarded"
