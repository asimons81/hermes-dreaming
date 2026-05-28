from __future__ import annotations

from pathlib import Path

from hermes_dreaming.artifact import DreamArtifact, DreamProposal, load_artifact, write_artifact
from hermes_dreaming.cli import main
from hermes_dreaming.diffing import render_artifact_diff


def _artifact(
    tmp_path: Path,
    *,
    artifact_id: str,
    workspace_root: Path,
    proposal: DreamProposal,
    report: str = "# Report\n\nOne proposal staged.",
) -> Path:
    artifact = DreamArtifact(
        artifact_id=artifact_id,
        created_at="2026-05-25T12:00:00Z",
        provider="offline-marker",
        status="staged",
        workspace_root=str(workspace_root),
        source_roots=[str(workspace_root / "sources")],
        report=report,
        sources=[],
        proposals=[proposal],
    )
    artifact_dir = tmp_path / artifact_id
    write_artifact(artifact, artifact_dir)
    return artifact_dir


def test_render_artifact_diff_shows_unified_diff_against_live_root(tmp_path: Path) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    (live_root / "memory.md").write_text("# MEMORY\n\n- Existing note\n", encoding="utf-8")

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
    artifact_dir = _artifact(tmp_path, artifact_id="artifact-diff", workspace_root=live_root, proposal=proposal)
    artifact = load_artifact(artifact_dir)

    output = render_artifact_diff(artifact, live_root=live_root)

    assert "Proposal proposal-memory" in output
    assert "target: memory -> memory.md" in output
    assert "mode: append_text" in output
    assert "summary: append memory note" in output
    assert "provenance: sessions/1.md:1" in output
    assert "--- a/memory.md" in output
    assert "+++ b/memory.md" in output
    assert "@@" in output
    assert "+- Keep updates short and concrete." in output


def test_diff_command_uses_workspace_root_when_live_root_is_omitted(tmp_path: Path, capsys) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    facts = live_root / "facts.jsonl"
    facts.write_text('{"existing": true}\n', encoding="utf-8")

    proposal = DreamProposal(
        id="proposal-fact",
        target_kind="fact",
        target_path="facts.jsonl",
        mode="jsonl_append",
        summary="append fact note",
        provenance=["sessions/2.md:4"],
        proposed_text='{"b": 2, "a": 1}',
        approved=True,
    )
    artifact_dir = _artifact(tmp_path, artifact_id="artifact-jsonl", workspace_root=live_root, proposal=proposal)

    assert main(["diff", str(artifact_dir)]) == 0
    output = capsys.readouterr().out

    assert "Proposal proposal-fact" in output
    assert "target: fact -> facts.jsonl" in output
    assert "mode: jsonl_append" in output
    assert "summary: append fact note" in output
    assert "provenance: sessions/2.md:4" in output
    assert '{"a": 1, "b": 2}' in output
    assert "--- a/facts.jsonl" in output
    assert "+++ b/facts.jsonl" in output


def test_diff_command_falls_back_to_report_when_live_root_is_missing(tmp_path: Path, capsys) -> None:
    missing_live_root = tmp_path / "missing-live-root"
    proposal = DreamProposal(
        id="proposal-memory",
        target_kind="memory",
        target_path="memory.md",
        mode="append_text",
        summary="append memory note",
        provenance=["sessions/3.md:1"],
        proposed_text="- Keep updates short and concrete.",
        approved=True,
    )
    artifact_dir = _artifact(
        tmp_path,
        artifact_id="artifact-fallback",
        workspace_root=missing_live_root,
        proposal=proposal,
        report="# Report\n\nFallback behavior should stay intact.",
    )

    assert main(["diff", str(artifact_dir)]) == 0
    output = capsys.readouterr().out

    assert "# Report" in output
    assert "Fallback behavior should stay intact." in output
    assert "- proposal-memory: memory -> memory.md [append_text]" in output
    assert "append memory note" in output
