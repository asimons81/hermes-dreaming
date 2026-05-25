from __future__ import annotations

import json
from pathlib import Path

from hermes_dreaming.artifact import load_artifact
from hermes_dreaming.cli import main


def _write_source_tree(root: Path) -> Path:
    sources = root / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "session-1.md").write_text(
        "# Session 1\n\nDREAM: memory: Keep updates short and concrete.\nDREAM: fact: {\"type\": \"preference\", \"key\": \"tone\", \"value\": \"casual\"}\nDREAM: skill: path=skills/review.md | Preserve review gates and backups.\n",
        encoding="utf-8",
    )
    return sources


def test_create_validate_apply_and_status_command_flow(tmp_path: Path, capsys) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    (live_root / "memory.md").write_text("# MEMORY\n", encoding="utf-8")
    (live_root / "user.md").write_text("# USER\n", encoding="utf-8")
    (live_root / "skills").mkdir()
    (live_root / "skills" / "review.md").write_text("# Review\n", encoding="utf-8")
    sources = _write_source_tree(tmp_path)
    artifact_root = tmp_path / "artifacts"
    backup_root = tmp_path / "backups"

    assert (
        main(
            [
                "create",
                "--live-root",
                str(live_root),
                "--artifact-root",
                str(artifact_root),
                "--source",
                str(sources),
            ]
        )
        == 0
    )
    create_output = capsys.readouterr().out.strip().splitlines()
    artifact_dir = Path(create_output[0].split(":", 1)[1].strip())
    assert artifact_dir.exists()

    assert main(["diff", str(artifact_dir)]) == 0
    diff_output = capsys.readouterr().out
    assert "memory" in diff_output.lower()
    assert "fact" in diff_output.lower()

    assert main(["validate", str(artifact_dir), "--live-root", str(live_root)]) == 0
    validate_output = capsys.readouterr().out
    assert "valid" in validate_output.lower()

    assert (
        main(
            [
                "apply",
                str(artifact_dir),
                "--live-root",
                str(live_root),
                "--backup-root",
                str(backup_root),
                "--approve",
                "all",
            ]
        )
        == 0
    )
    apply_output = capsys.readouterr().out
    assert "applied" in apply_output.lower()

    memory = (live_root / "memory.md").read_text(encoding="utf-8")
    assert "Keep updates short and concrete." in memory
    facts = (live_root / "facts.jsonl").read_text(encoding="utf-8").splitlines()
    assert any(json.loads(line)["key"] == "tone" for line in facts)
    skill = (live_root / "skills" / "review.md").read_text(encoding="utf-8")
    assert "Preserve review gates and backups." in skill
    assert (backup_root / "memory.md").exists()
    assert load_artifact(artifact_dir).status == "applied"

    assert main(["status", "--artifact-root", str(artifact_root)]) == 0
    status_output = capsys.readouterr().out
    assert "applied" in status_output.lower()


def test_discard_command_archives_artifact(tmp_path: Path, capsys) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    (live_root / "memory.md").write_text("# MEMORY\n", encoding="utf-8")
    sources = _write_source_tree(tmp_path)
    artifact_root = tmp_path / "artifacts"
    archive_root = tmp_path / "archive"

    assert (
        main(
            [
                "create",
                "--live-root",
                str(live_root),
                "--artifact-root",
                str(artifact_root),
                "--source",
                str(sources),
            ]
        )
        == 0
    )
    artifact_dir = Path(capsys.readouterr().out.strip().splitlines()[0].split(":", 1)[1].strip())

    assert main(["discard", str(artifact_dir), "--archive-root", str(archive_root)]) == 0
    discard_output = capsys.readouterr().out
    assert "discarded" in discard_output.lower()

    assert not artifact_dir.exists()
    archived_dir = archive_root / artifact_dir.name
    assert archived_dir.exists()
    assert (live_root / "memory.md").read_text(encoding="utf-8") == "# MEMORY\n"
