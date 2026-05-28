from __future__ import annotations

from pathlib import Path

import pytest

from hermes_dreaming.artifact import DreamArtifact, DreamProposal, load_artifact, write_artifact
from hermes_dreaming import apply as apply_module
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

    loaded = load_artifact(artifact_dir)
    assert loaded.status == "applied"
    assert loaded.applied_proposal_ids == [proposal.id]
    assert loaded.backup_paths == [str(backup_root / "memory.md")]
    assert loaded.apply_started_at is not None
    assert loaded.apply_finished_at is not None
    assert loaded.applied_at is not None
    assert loaded.apply_errors == []
    assert loaded.validation_errors == []
    assert loaded.proposals[0].applied is True


def test_apply_rolls_back_and_records_audit_when_later_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    memory = live_root / "memory.md"
    memory.write_text("# MEMORY\n\n- Existing note\n", encoding="utf-8")
    facts = live_root / "facts.jsonl"
    facts.write_text('{"key": "tone", "value": "direct"}\n', encoding="utf-8")

    first = DreamProposal(
        id="proposal-memory",
        target_kind="memory",
        target_path="memory.md",
        mode="append_text",
        summary="append memory note",
        provenance=["sessions/1.md:1"],
        proposed_text="- Keep updates short and concrete.",
        approved=True,
    )
    second = DreamProposal(
        id="proposal-notes",
        target_kind="skill",
        target_path="notes.md",
        mode="append_text",
        summary="create notes file",
        provenance=["sessions/1.md:2"],
        proposed_text="- Add a loose note about apply rollback.",
        approved=True,
    )
    third = DreamProposal(
        id="proposal-fact",
        target_kind="fact",
        target_path="facts.jsonl",
        mode="jsonl_append",
        summary="append fact",
        provenance=["sessions/1.md:3"],
        proposed_text='{"key": "tone", "value": "casual"}',
        approved=True,
    )
    artifact_dir, _created_artifact = _artifact(tmp_path, first)
    artifact = load_artifact(artifact_dir)
    artifact.proposals.extend([second, third])
    write_artifact(artifact, artifact_dir)
    backup_root = tmp_path / "backups"

    original_atomic_write_text = apply_module.atomic_write_text
    calls = {"count": 0}

    def corrupt_third_write(path: Path, text: str) -> None:
        calls["count"] += 1
        if calls["count"] in {1, 2}:
            original_atomic_write_text(path, text)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("BROKEN\n", encoding="utf-8")

    monkeypatch.setattr(apply_module, "atomic_write_text", corrupt_third_write)

    with pytest.raises(DreamApplyError, match="verification failed"):
        apply_artifact(artifact_dir, live_root=live_root, backup_root=backup_root, approve_all=True)

    assert memory.read_text(encoding="utf-8") == "# MEMORY\n\n- Existing note\n"
    assert facts.read_text(encoding="utf-8") == '{"key": "tone", "value": "direct"}\n'
    assert (backup_root / "memory.md").exists()
    assert (backup_root / "facts.jsonl").exists()

    loaded = load_artifact(artifact_dir)
    assert loaded.status == "validated"
    assert loaded.applied_proposal_ids == [first.id, second.id]
    assert loaded.backup_paths == [str(backup_root / "memory.md"), str(backup_root / "facts.jsonl")]
    assert loaded.apply_started_at is not None
    assert loaded.apply_finished_at is not None
    assert loaded.apply_errors
    assert any("verification failed" in error.lower() for error in loaded.apply_errors)
    assert loaded.applied_at is None
    assert loaded.proposals[0].applied is False
    assert loaded.proposals[1].applied is False


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
