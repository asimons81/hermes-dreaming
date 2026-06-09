from __future__ import annotations

from pathlib import Path

import pytest

from hermes_dreaming.artifact import DreamArtifact, DreamProposal, load_artifact, write_artifact
from hermes_dreaming import apply as apply_module
from hermes_dreaming.apply import apply_artifact, discard_artifact, DreamApplyError


def _has_exact_child(parent: Path, name: str) -> bool:
    return any(child.name == name for child in parent.iterdir())


def _case_sensitive_dir(path: Path) -> bool:
    probe = path / "CaseSensitivityProbe"
    probe.write_text("probe", encoding="utf-8")
    try:
        return not (path / "casesensitivityprobe").exists()
    finally:
        probe.unlink(missing_ok=True)


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


def test_apply_prefers_existing_uppercase_memory_file(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    memory = live_root / "MEMORY.md"
    memory.write_text("# MEMORY\n\n- Existing uppercase note\n", encoding="utf-8")

    proposal = DreamProposal(
        id="proposal-memory",
        target_kind="memory",
        target_path="memory.md",
        mode="append_text",
        summary="append memory note",
        provenance=["sessions/1.md:1"],
        proposed_text="- Keep uppercase installs on the existing file.",
        approved=True,
    )
    artifact_dir, _artifact_result = _artifact(tmp_path, proposal)
    backup_root = tmp_path / "backups"

    result = apply_artifact(artifact_dir, live_root=live_root, backup_root=backup_root, approve_all=True)

    assert result.status == "applied"
    assert memory.read_text(encoding="utf-8").strip().endswith("- Keep uppercase installs on the existing file.")
    assert not _has_exact_child(live_root, "memory.md")
    assert (backup_root / "MEMORY.md").exists()


def test_apply_prefers_uppercase_memory_when_both_cases_exist(tmp_path: Path) -> None:
    if not _case_sensitive_dir(tmp_path):
        pytest.skip("cannot create separate MEMORY.md and memory.md entries on a case-insensitive filesystem")

    live_root = tmp_path / "live"
    live_root.mkdir()
    upper_memory = live_root / "MEMORY.md"
    lower_memory = live_root / "memory.md"
    upper_memory.write_text("# MEMORY\n\n- Canonical uppercase note\n", encoding="utf-8")
    lower_memory.write_text("# memory\n\n- stale lowercase duplicate\n", encoding="utf-8")

    proposal = DreamProposal(
        id="proposal-memory",
        target_kind="memory",
        target_path="memory.md",
        mode="append_text",
        summary="append memory note",
        provenance=["sessions/1.md:1"],
        proposed_text="- Keep mixed-case installs on the canonical uppercase file.",
        approved=True,
    )
    artifact_dir, _artifact_result = _artifact(tmp_path, proposal)
    backup_root = tmp_path / "backups"

    result = apply_artifact(artifact_dir, live_root=live_root, backup_root=backup_root, approve_all=True)

    assert result.status == "applied"
    assert upper_memory.read_text(encoding="utf-8").strip().endswith(
        "- Keep mixed-case installs on the canonical uppercase file."
    )
    assert lower_memory.read_text(encoding="utf-8") == "# memory\n\n- stale lowercase duplicate\n"
    assert (backup_root / "MEMORY.md").exists()


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
        target_path="skills/notes.md",
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


def test_apply_honors_persisted_approval_state(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    memory = live_root / "memory.md"
    memory.write_text("# MEMORY\n\n- Existing note\n", encoding="utf-8")

    approved = DreamProposal(
        id="proposal-memory",
        target_kind="memory",
        target_path="memory.md",
        mode="append_text",
        summary="append memory note",
        provenance=["sessions/1.md:1"],
        proposed_text="- Keep updates short and concrete.",
        approved=True,
    )
    pending = DreamProposal(
        id="proposal-user",
        target_kind="user",
        target_path="user.md",
        mode="append_text",
        summary="append user note",
        provenance=["sessions/1.md:2"],
        proposed_text="- Prefer concise status updates.",
        approved=False,
    )
    artifact = DreamArtifact(
        artifact_id="artifact-approval-state",
        created_at="2026-05-25T12:00:00Z",
        provider="offline-marker",
        status="validated",
        workspace_root=str(live_root),
        source_roots=[str(live_root / "sources")],
        report="# Report",
        sources=[],
        proposals=[approved, pending],
    )
    artifact_dir = tmp_path / "artifact-approval-state"
    write_artifact(artifact, artifact_dir)
    backup_root = tmp_path / "backups"

    result = apply_artifact(artifact_dir, live_root=live_root, backup_root=backup_root, approve_all=False)

    assert result.status == "applied"
    assert result.applied_proposal_ids == [approved.id]
    assert memory.read_text(encoding="utf-8").strip().endswith("- Keep updates short and concrete.")
    assert not (live_root / "user.md").exists()

    loaded = load_artifact(artifact_dir)
    assert loaded.proposals[0].applied is True
    assert loaded.proposals[1].applied is False
    assert any(event["action"] == "applied" for event in loaded.audit_events)


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


def test_apply_dry_run_writes_nothing_to_live_state_and_creates_no_backup(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    memory = live_root / "memory.md"
    original_text = "# MEMORY\n\n- Existing note\n"
    memory.write_text(original_text, encoding="utf-8")

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
    artifact_dir, _artifact_result = _artifact(tmp_path, proposal)
    backup_root = tmp_path / "backups"

    result = apply_artifact(
        artifact_dir,
        live_root=live_root,
        backup_root=backup_root,
        approve_all=True,
        dry_run=True,
    )

    # Live state untouched.
    assert memory.read_text(encoding="utf-8") == original_text
    # No backups were created.
    assert not (backup_root / "memory.md").exists()
    # Artifact status was NOT changed to applied.
    loaded = load_artifact(artifact_dir)
    assert loaded.status != "applied"
    # Report is attached on the returned artifact.
    assert result.dry_run_report is not None
    assert result.dry_run_report.would_apply_proposal_ids == [proposal.id]
    assert result.dry_run_report.would_write_targets == [str(memory)]
    assert result.dry_run_report.would_backup_paths == [str(backup_root / "memory.md")]
    # Report is ephemeral — not serialized into manifest.
    assert "dry_run_report" not in loaded.to_dict()


def test_apply_dry_run_reports_would_skip_proposals_when_filter_excludes_them(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    (live_root / "memory.md").write_text("# MEMORY\n", encoding="utf-8")

    high_memory = DreamProposal(
        id="proposal-memory-high",
        target_kind="memory",
        target_path="memory.md",
        mode="append_text",
        summary="high priority memory",
        provenance=["sessions/1.md:1"],
        proposed_text="- High memory",
        approved=True,
        priority="high",
    )
    low_user = DreamProposal(
        id="proposal-user-low",
        target_kind="user",
        target_path="user.md",
        mode="append_text",
        summary="low priority user",
        provenance=["sessions/1.md:2"],
        proposed_text="- Low user",
        approved=True,
        priority="low",
    )
    artifact = DreamArtifact(
        artifact_id="artifact-filter-dry-run",
        created_at="2026-05-25T12:00:00Z",
        provider="offline-marker",
        status="validated",
        workspace_root=str(live_root),
        source_roots=[str(live_root / "sources")],
        report="# Report",
        sources=[],
        proposals=[high_memory, low_user],
    )
    artifact_dir = tmp_path / "artifact-filter-dry-run"
    write_artifact(artifact, artifact_dir)
    backup_root = tmp_path / "backups"

    result = apply_artifact(
        artifact_dir,
        live_root=live_root,
        backup_root=backup_root,
        approve_all=True,
        dry_run=True,
        priority_filter={"high"},
        target_kind_filter={"memory"},
    )

    report = result.dry_run_report
    assert report is not None
    assert report.would_apply_proposal_ids == [high_memory.id]
    # Both filters excluded the user proposal, but the priority filter caught it first.
    assert "proposal-user-low" in report.filtered_out_priority or "proposal-user-low" in report.filtered_out_target_kind
    # Live state untouched.
    assert (live_root / "memory.md").read_text(encoding="utf-8") == "# MEMORY\n"
    assert not (live_root / "user.md").exists()


def test_apply_priority_filter_includes_only_matching_proposals(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    (live_root / "memory.md").write_text("# MEMORY\n", encoding="utf-8")
    (live_root / "user.md").write_text("# USER\n", encoding="utf-8")

    high = DreamProposal(
        id="proposal-high",
        target_kind="memory",
        target_path="memory.md",
        mode="append_text",
        summary="high memory",
        provenance=["sessions/1.md:1"],
        proposed_text="- High note",
        approved=True,
        priority="high",
    )
    low = DreamProposal(
        id="proposal-low",
        target_kind="user",
        target_path="user.md",
        mode="append_text",
        summary="low user",
        provenance=["sessions/1.md:2"],
        proposed_text="- Low note",
        approved=True,
        priority="low",
    )
    artifact = DreamArtifact(
        artifact_id="artifact-priority-filter",
        created_at="2026-05-25T12:00:00Z",
        provider="offline-marker",
        status="validated",
        workspace_root=str(live_root),
        source_roots=[str(live_root / "sources")],
        report="# Report",
        sources=[],
        proposals=[high, low],
    )
    artifact_dir = tmp_path / "artifact-priority-filter"
    write_artifact(artifact, artifact_dir)
    backup_root = tmp_path / "backups"

    result = apply_artifact(
        artifact_dir,
        live_root=live_root,
        backup_root=backup_root,
        approve_all=True,
        priority_filter={"high"},
    )

    assert result.status == "applied"
    assert result.applied_proposal_ids == [high.id]
    memory_text = (live_root / "memory.md").read_text(encoding="utf-8")
    assert "- High note" in memory_text
    # Low-priority proposal was filtered out and stays approved.
    user_text = (live_root / "user.md").read_text(encoding="utf-8")
    assert user_text == "# USER\n"
    loaded = load_artifact(artifact_dir)
    assert loaded.proposals[1].approved is True
    assert loaded.proposals[1].applied is False


def test_apply_target_kind_filter_includes_only_matching_proposals(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    (live_root / "memory.md").write_text("# MEMORY\n", encoding="utf-8")
    (live_root / "user.md").write_text("# USER\n", encoding="utf-8")

    memory = DreamProposal(
        id="proposal-memory",
        target_kind="memory",
        target_path="memory.md",
        mode="append_text",
        summary="memory",
        provenance=["sessions/1.md:1"],
        proposed_text="- Memory note",
        approved=True,
    )
    user = DreamProposal(
        id="proposal-user",
        target_kind="user",
        target_path="user.md",
        mode="append_text",
        summary="user",
        provenance=["sessions/1.md:2"],
        proposed_text="- User note",
        approved=True,
    )
    artifact = DreamArtifact(
        artifact_id="artifact-target-kind-filter",
        created_at="2026-05-25T12:00:00Z",
        provider="offline-marker",
        status="validated",
        workspace_root=str(live_root),
        source_roots=[str(live_root / "sources")],
        report="# Report",
        sources=[],
        proposals=[memory, user],
    )
    artifact_dir = tmp_path / "artifact-target-kind-filter"
    write_artifact(artifact, artifact_dir)
    backup_root = tmp_path / "backups"

    result = apply_artifact(
        artifact_dir,
        live_root=live_root,
        backup_root=backup_root,
        approve_all=True,
        target_kind_filter={"memory"},
    )

    assert result.status == "applied"
    assert result.applied_proposal_ids == [memory.id]
    assert "- Memory note" in (live_root / "memory.md").read_text(encoding="utf-8")
    assert (live_root / "user.md").read_text(encoding="utf-8") == "# USER\n"


def test_apply_filters_compose_with_dry_run(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    (live_root / "memory.md").write_text("# MEMORY\n", encoding="utf-8")
    (live_root / "user.md").write_text("# USER\n", encoding="utf-8")
    (live_root / "skills").mkdir()
    (live_root / "skills" / "review.md").write_text("# Review\n", encoding="utf-8")

    high_memory = DreamProposal(
        id="proposal-high-memory",
        target_kind="memory",
        target_path="memory.md",
        mode="append_text",
        summary="high memory",
        provenance=["sessions/1.md:1"],
        proposed_text="- High memory",
        approved=True,
        priority="high",
    )
    high_user = DreamProposal(
        id="proposal-high-user",
        target_kind="user",
        target_path="user.md",
        mode="append_text",
        summary="high user",
        provenance=["sessions/1.md:2"],
        proposed_text="- High user",
        approved=True,
        priority="high",
    )
    low_skill = DreamProposal(
        id="proposal-low-skill",
        target_kind="skill",
        target_path="skills/review.md",
        mode="append_text",
        summary="low skill",
        provenance=["sessions/1.md:3"],
        proposed_text="- Low skill",
        approved=True,
        priority="low",
    )
    artifact = DreamArtifact(
        artifact_id="artifact-composed-filters",
        created_at="2026-05-25T12:00:00Z",
        provider="offline-marker",
        status="validated",
        workspace_root=str(live_root),
        source_roots=[str(live_root / "sources")],
        report="# Report",
        sources=[],
        proposals=[high_memory, high_user, low_skill],
    )
    artifact_dir = tmp_path / "artifact-composed-filters"
    write_artifact(artifact, artifact_dir)
    backup_root = tmp_path / "backups"

    result = apply_artifact(
        artifact_dir,
        live_root=live_root,
        backup_root=backup_root,
        approve_all=True,
        dry_run=True,
        priority_filter={"high"},
        target_kind_filter={"memory"},
    )

    report = result.dry_run_report
    assert report is not None
    # Only high_memory matches both filters.
    assert report.would_apply_proposal_ids == [high_memory.id]
    # high_user is filtered by target_kind, low_skill by priority.
    assert "proposal-high-user" in report.filtered_out_target_kind
    assert "proposal-low-skill" in report.filtered_out_priority
    # Live state untouched.
    assert (live_root / "memory.md").read_text(encoding="utf-8") == "# MEMORY\n"
    assert (live_root / "user.md").read_text(encoding="utf-8") == "# USER\n"
