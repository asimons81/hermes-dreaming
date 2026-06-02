from __future__ import annotations

from importlib import import_module
from pathlib import Path
from unittest.mock import MagicMock, patch

from hermes_dreaming.artifact import DreamArtifact, DreamProposal, SourceSnapshot, load_artifact, write_artifact
from hermes_dreaming.cli import main
from hermes_dreaming.commands.install_cron import DEFAULT_SCHEDULE, JOB_NAME, SCRIPT_NAME, handle as install_cron_handle

install_cron_module = import_module("hermes_dreaming.commands.install_cron")


def _write_source_tree(root: Path) -> Path:
    sources = root / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / "session-1.md").write_text(
        "# Session 1\n\nDREAM: memory: Keep updates short and concrete.\nDREAM: fact: {\"type\": \"preference\", \"key\": \"tone\", \"value\": \"casual\"}\n",
        encoding="utf-8",
    )
    return sources


def _write_artifact(artifact_root: Path, *, artifact_id: str, status: str) -> Path:
    artifact = DreamArtifact(
        artifact_id=artifact_id,
        created_at="2026-05-25T12:00:00Z",
        provider="offline-marker",
        status=status,
        workspace_root=str(artifact_root),
        source_roots=[str(artifact_root / "sources")],
        report="# Report\n",
        sources=[
            SourceSnapshot(
                path="sources/session-1.md",
                kind="session",
                content="DREAM: memory: Keep updates short and concrete.\n",
                sha256="f" * 64,
                line_count=1,
            )
        ],
        proposals=[
            DreamProposal(
                id=f"{artifact_id}-proposal",
                target_kind="memory",
                target_path="memory.md",
                mode="append_text",
                summary="append memory note",
                provenance=["sources/session-1.md:1"],
                proposed_text="- Keep updates short and concrete.",
                approved=True,
            )
        ],
    )
    artifact_dir = artifact_root / artifact_id
    write_artifact(artifact, artifact_dir)
    return artifact_dir


def _patch_hermes_home(monkeypatch, tmp_path: Path) -> Path:
    home = tmp_path / ".hermes"
    (home / "scripts").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(install_cron_module, "get_hermes_home", lambda: home)
    return home


def test_review_command_stages_artifact_without_touching_live_files(tmp_path: Path, capsys) -> None:
    live_root = tmp_path / "live"
    live_root.mkdir()
    (live_root / "memory.md").write_text("# MEMORY\n", encoding="utf-8")
    (live_root / "user.md").write_text("# USER\n", encoding="utf-8")
    (live_root / "skills").mkdir()
    (live_root / "skills" / "review.md").write_text("# Review\n", encoding="utf-8")

    sources = _write_source_tree(tmp_path)
    artifact_root = tmp_path / "artifacts"

    assert (
        main(
            [
                "review",
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

    output = capsys.readouterr().out
    artifact_dir = Path(output.splitlines()[0].split(":", 1)[1].strip())
    artifact = load_artifact(artifact_dir)

    assert artifact_dir.exists()
    assert artifact.status == "staged"
    assert "dry-run" in output.lower() or "review" in output.lower()
    assert (live_root / "memory.md").read_text(encoding="utf-8") == "# MEMORY\n"
    assert (live_root / "user.md").read_text(encoding="utf-8") == "# USER\n"


def test_compact_command_moves_terminal_artifacts_into_archive(tmp_path: Path, capsys) -> None:
    artifact_root = tmp_path / "artifacts"
    archive_root = tmp_path / "archive"
    artifact_root.mkdir()

    staged_dir = _write_artifact(artifact_root, artifact_id="artifact-staged", status="staged")
    applied_dir = _write_artifact(artifact_root, artifact_id="artifact-applied", status="applied")
    discarded_dir = _write_artifact(artifact_root, artifact_id="artifact-discarded", status="discarded")

    assert (
        main(
            [
                "compact",
                "--artifact-root",
                str(artifact_root),
                "--archive-root",
                str(archive_root),
            ]
        )
        == 0
    )

    output = capsys.readouterr().out
    assert "archived" in output.lower() or "moved" in output.lower()
    assert staged_dir.exists()
    assert not applied_dir.exists()
    assert not discarded_dir.exists()
    assert (archive_root / "artifact-applied").exists()
    assert (archive_root / "artifact-discarded").exists()
    assert load_artifact(archive_root / "artifact-applied").status == "applied"
    assert load_artifact(archive_root / "artifact-discarded").status == "discarded"


def test_install_cron_registers_digest_job_and_writes_script(tmp_path: Path, monkeypatch, capsys) -> None:
    home = _patch_hermes_home(monkeypatch, tmp_path)
    mock_cron = MagicMock()
    mock_cron.list_jobs.return_value = []
    mock_cron.create_job.return_value = {
        "id": "job-123",
        "name": JOB_NAME,
        "schedule_display": "At 03:00 every day",
        "next_run_at": "2099-01-02T03:00:00+00:00",
    }

    with patch.dict("sys.modules", {"cron.jobs": mock_cron}):
        result = install_cron_handle()

    assert "registered" in result.lower()
    call_kwargs = mock_cron.create_job.call_args.kwargs
    assert call_kwargs["prompt"] == "Hermes Dreaming daily digest"
    assert call_kwargs["schedule"] == DEFAULT_SCHEDULE
    assert call_kwargs["name"] == JOB_NAME
    assert call_kwargs["deliver"] == "local"
    assert call_kwargs["script"] == SCRIPT_NAME
    assert call_kwargs["no_agent"] is True
    assert call_kwargs["workdir"] == str(install_cron_module._repo_root())

    script_path = home / "scripts" / SCRIPT_NAME
    assert script_path.exists()
    assert "Hermes Dreaming daily digest" in script_path.read_text(encoding="utf-8")


def test_install_cron_reuses_existing_job_when_config_matches(tmp_path: Path, monkeypatch) -> None:
    _patch_hermes_home(monkeypatch, tmp_path)
    mock_cron = MagicMock()
    mock_cron.list_jobs.return_value = [
        {
            "id": "job-existing",
            "name": JOB_NAME,
            "schedule_display": "At 03:00 every day",
            "enabled": True,
            "next_run_at": "2099-01-02T03:00:00+00:00",
            "prompt": "Hermes Dreaming daily digest",
            "schedule": DEFAULT_SCHEDULE,
            "deliver": "local",
            "script": SCRIPT_NAME,
            "no_agent": True,
            "workdir": str(install_cron_module._repo_root()),
        }
    ]

    with patch.dict("sys.modules", {"cron.jobs": mock_cron}):
        result = install_cron_handle()

    assert "Already installed" in result
    mock_cron.create_job.assert_not_called()
    mock_cron.update_job.assert_not_called()


def test_install_cron_refreshes_legacy_prompt_job(tmp_path: Path, monkeypatch) -> None:
    _patch_hermes_home(monkeypatch, tmp_path)
    mock_cron = MagicMock()
    mock_cron.list_jobs.return_value = [
        {
            "id": "job-legacy",
            "name": JOB_NAME,
            "schedule_display": "At 03:00 every day",
            "enabled": True,
            "next_run_at": "2099-01-02T03:00:00+00:00",
            "prompt": "/dreaming review",
            "schedule": DEFAULT_SCHEDULE,
            "deliver": "local",
            "no_agent": False,
        }
    ]
    mock_cron.update_job.return_value = {
        "id": "job-legacy",
        "name": JOB_NAME,
        "schedule_display": "At 03:00 every day",
        "enabled": True,
        "next_run_at": "2099-01-03T03:00:00+00:00",
        "prompt": "Hermes Dreaming daily digest",
        "schedule": DEFAULT_SCHEDULE,
        "deliver": "local",
        "script": SCRIPT_NAME,
        "no_agent": True,
        "workdir": str(install_cron_module._repo_root()),
    }

    with patch.dict("sys.modules", {"cron.jobs": mock_cron}):
        result = install_cron_handle()

    assert "updated" in result.lower()
    mock_cron.create_job.assert_not_called()
    mock_cron.update_job.assert_called_once()
    update_kwargs = mock_cron.update_job.call_args.args[1]
    assert update_kwargs["prompt"] == "Hermes Dreaming daily digest"
    assert update_kwargs["deliver"] == "local"
    assert update_kwargs["script"] == SCRIPT_NAME
    assert update_kwargs["no_agent"] is True
    assert update_kwargs["workdir"] == str(install_cron_module._repo_root())
