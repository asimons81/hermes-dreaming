from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from hermes_dreaming.artifact import DreamArtifact, DreamProposal, SourceSnapshot, load_artifact, write_artifact


def test_artifact_round_trip(tmp_path: Path) -> None:
    source = SourceSnapshot(
        path="sessions/2026-05-25.md",
        kind="session",
        content="DREAM: memory: Keep updates short and concrete.\n",
        sha256=sha256(b"DREAM: memory: Keep updates short and concrete.\n").hexdigest(),
        line_count=1,
    )
    proposal = DreamProposal(
        id="proposal-memory",
        target_kind="memory",
        target_path="memory.md",
        mode="append_text",
        summary="append memory note",
        provenance=["sessions/2026-05-25.md:1"],
        proposed_text="- Keep updates short and concrete.",
        approved=True,
    )
    artifact = DreamArtifact(
        artifact_id="artifact-001",
        created_at="2026-05-25T12:00:00Z",
        provider="offline-marker",
        status="staged",
        workspace_root=str(tmp_path),
        source_roots=[str(tmp_path / "sources")],
        report="# Report\n\nOne proposal staged.",
        sources=[source],
        proposals=[proposal],
    )

    artifact_dir = tmp_path / "artifact"
    write_artifact(artifact, artifact_dir)

    loaded = load_artifact(artifact_dir)
    assert loaded == artifact
    assert (artifact_dir / "manifest.json").exists()
    assert (artifact_dir / "REPORT.md").read_text(encoding="utf-8") == artifact.report
    assert (artifact_dir / "sources.jsonl").exists()
