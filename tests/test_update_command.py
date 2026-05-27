from __future__ import annotations

import subprocess
from pathlib import Path
import types

from hermes_dreaming.commands.update import handle
from hermes_dreaming.cli import main


def _run_git(args: list[str], *, cwd: Path) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise AssertionError(proc.stderr or proc.stdout or f"git {' '.join(args)} failed")
    return proc.stdout.strip()


def _init_repo(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    _run_git(["init", "--bare", str(remote)], cwd=tmp_path)
    _run_git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=remote)
    repo.mkdir()
    try:
        _run_git(["init", "-b", "main"], cwd=repo)
    except AssertionError:
        _run_git(["init"], cwd=repo)
        _run_git(["checkout", "-b", "main"], cwd=repo)
    _run_git(["config", "user.name", "Hermes Test"], cwd=repo)
    _run_git(["config", "user.email", "hermes@test.local"], cwd=repo)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_smoke.py").write_text("def test_smoke():\n    assert True\n", encoding="utf-8")
    (repo / "README.md").write_text("# test repo\n", encoding="utf-8")
    _run_git(["add", "."], cwd=repo)
    _run_git(["commit", "-m", "initial commit"], cwd=repo)
    _run_git(["remote", "add", "origin", str(remote)], cwd=repo)
    _run_git(["push", "-u", "origin", "main"], cwd=repo)
    return repo, remote


def _add_remote_commit(remote: Path, tmp_path: Path) -> str:
    other = tmp_path / "other"
    _run_git(["clone", "-b", "main", str(remote), str(other)], cwd=tmp_path)
    _run_git(["config", "user.name", "Hermes Test"], cwd=other)
    _run_git(["config", "user.email", "hermes@test.local"], cwd=other)
    (other / "update.txt").write_text("update\n", encoding="utf-8")
    _run_git(["add", "update.txt"], cwd=other)
    _run_git(["commit", "-m", "upstream update"], cwd=other)
    _run_git(["push"], cwd=other)
    return _run_git(["rev-parse", "HEAD"], cwd=other)


def test_update_check_reports_up_to_date(tmp_path: Path) -> None:
    repo, _remote = _init_repo(tmp_path)

    result = handle(repo_root=repo, check=True)

    assert result.success is True
    assert result.checked_only is True
    assert result.updated is False
    assert result.behind == 0
    assert "Already up to date." in result.message


def test_update_fast_forwards_and_verifies(tmp_path: Path) -> None:
    repo, remote = _init_repo(tmp_path)
    updated_rev = _add_remote_commit(remote, tmp_path)

    result = handle(repo_root=repo)

    assert result.success is True
    assert result.updated is True
    assert result.verified is True
    assert result.behind == 1
    assert _run_git(["rev-parse", "HEAD"], cwd=repo) == updated_rev
    assert (repo / "update.txt").read_text(encoding="utf-8") == "update\n"


def test_update_refuses_dirty_tree(tmp_path: Path) -> None:
    repo, _remote = _init_repo(tmp_path)
    (repo / "README.md").write_text("# dirty repo\n", encoding="utf-8")

    result = handle(repo_root=repo)

    assert result.success is False
    assert result.dirty is True
    assert "dirty" in result.message.lower()


def test_cli_update_wires_through_parser(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_update_command(**kwargs):
        captured.update(kwargs)
        return types.SimpleNamespace(
            success=True,
            message="Updated from abc1234 to def5678 successfully.",
            repo_root=kwargs["repo_root"],
            remote=kwargs["remote"],
            branch=kwargs["branch"],
            current_rev="abc1234",
            upstream_rev="def5678",
            behind=1,
            ahead=0,
            dirty=False,
            checked_only=kwargs["check"],
            updated=not kwargs["check"],
            verified=not kwargs["check"] and kwargs["verify"],
        )

    monkeypatch.setattr("hermes_dreaming.cli.update_command", fake_update_command)
    monkeypatch.setattr("hermes_dreaming.cli.render_update_result", lambda result: f"rendered:{result.message}")

    assert main(["update", "--check", "--remote", "upstream", "--branch", "dev", "--no-verify"]) == 0
    assert captured["remote"] == "upstream"
    assert captured["branch"] == "dev"
    assert captured["check"] is True
    assert captured["verify"] is False
    assert captured["repo_root"].name == "hermes-dreaming"
