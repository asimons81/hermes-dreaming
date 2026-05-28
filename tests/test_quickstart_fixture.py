from __future__ import annotations

from pathlib import Path

from hermes_dreaming.analyze import DreamRunConfig, create_dream_artifact


def test_quickstart_fixture_runs_offline_without_api_key(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    fixture_root = repo_root / "examples" / "quickstart"
    live_root = fixture_root / "live"
    source_root = fixture_root / "sources"
    artifact_root = tmp_path / "artifacts"

    result = create_dream_artifact(
        DreamRunConfig(
            live_root=live_root,
            artifact_root=artifact_root,
            source_paths=[source_root],
        )
    )

    assert result.artifact.provider == "offline-marker"
    assert result.artifact.status == "staged"
    assert result.validation_errors == []
    assert result.artifact_dir.exists()
    assert (result.artifact_dir / "manifest.json").exists()
    assert (result.artifact_dir / "REPORT.md").exists()
    assert (result.artifact_dir / "sources.jsonl").exists()
    assert (result.artifact_dir / "proposals.jsonl").exists()
    assert {proposal.target_kind for proposal in result.artifact.proposals} == {"fact", "memory", "skill", "user"}

    docs_and_fixture_files = [
        repo_root / "README.md",
        repo_root / "docs" / "quickstart.md",
        fixture_root / "README.md",
        live_root / "memory.md",
        live_root / "user.md",
        live_root / "facts.jsonl",
        live_root / "skills" / "review.md",
        source_root / "session-1.md",
        source_root / "session-2.md",
    ]
    for path in docs_and_fixture_files:
        text = path.read_text(encoding="utf-8")
        assert "/home/tony" not in text

    assert "no api key" in (repo_root / "docs" / "quickstart.md").read_text(encoding="utf-8").lower()
    assert "no api key" in (fixture_root / "README.md").read_text(encoding="utf-8").lower()
