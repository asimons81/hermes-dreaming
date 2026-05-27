from __future__ import annotations

from dataclasses import dataclass
import os
import subprocess
import sys
from pathlib import Path

DEFAULT_REMOTE = "origin"
DEFAULT_BRANCH = "main"
_PYTEST_CACHE_DIR = "/tmp/hermes-dreaming-update-pytest-cache"


@dataclass(slots=True)
class UpdateResult:
    success: bool
    repo_root: Path
    remote: str
    branch: str
    current_rev: str
    upstream_rev: str | None
    behind: int
    ahead: int
    dirty: bool
    checked_only: bool
    updated: bool
    verified: bool
    message: str


def _discover_repo_root(start: Path | None = None) -> Path:
    if start is not None:
        candidate = Path(start).resolve()
        return candidate if candidate.is_dir() else candidate.parent

    candidate = Path(__file__).resolve()
    for path in [candidate, *candidate.parents]:
        if (path / "pyproject.toml").exists() and (path / "plugin.yaml").exists():
            return path
    raise RuntimeError("Could not locate the Hermes Dreaming repository root.")


def _run_git(args: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(["git", *args], cwd=cwd, text=True, capture_output=True)
    if proc.returncode != 0:
        details = proc.stderr.strip() or proc.stdout.strip() or f"git {' '.join(args)} failed"
        raise RuntimeError(details)
    return proc


def _git_output(args: list[str], *, cwd: Path) -> str:
    return _run_git(args, cwd=cwd).stdout.strip()


def _format_update_report(result: UpdateResult) -> str:
    lines = ["# Hermes Dreaming update", ""]
    lines.extend(
        [
            f"- Repo: `{result.repo_root}`",
            f"- Remote: `{result.remote}`",
            f"- Branch: `{result.branch}`",
            f"- Current: `{result.current_rev[:7]}`",
        ]
    )
    if result.upstream_rev:
        lines.append(f"- Upstream: `{result.upstream_rev[:7]}`")
    lines.extend(
        [
            f"- Ahead: `{result.ahead}`",
            f"- Behind: `{result.behind}`",
            f"- Dirty: `{result.dirty}`",
            f"- Mode: `{ 'check' if result.checked_only else 'update' }`",
            f"- Updated: `{result.updated}`",
            f"- Verified: `{result.verified}`",
            f"- Status: `{ 'ok' if result.success else 'failed' }`",
            "",
            result.message,
            "",
        ]
    )
    return "\n".join(lines)


def handle(
    *,
    repo_root: Path | None = None,
    remote: str = DEFAULT_REMOTE,
    branch: str = DEFAULT_BRANCH,
    check: bool = False,
    verify: bool = True,
) -> UpdateResult:
    repo_root = _discover_repo_root(repo_root)

    try:
        current_rev = _git_output(["rev-parse", "HEAD"], cwd=repo_root)
        dirty = bool(_git_output(["status", "--porcelain"], cwd=repo_root))
    except Exception as exc:
        return UpdateResult(
            success=False,
            repo_root=repo_root,
            remote=remote,
            branch=branch,
            current_rev="unknown",
            upstream_rev=None,
            behind=0,
            ahead=0,
            dirty=False,
            checked_only=check,
            updated=False,
            verified=False,
            message=f"Could not inspect repository state: {exc}",
        )

    if dirty:
        return UpdateResult(
            success=False,
            repo_root=repo_root,
            remote=remote,
            branch=branch,
            current_rev=current_rev,
            upstream_rev=None,
            behind=0,
            ahead=0,
            dirty=True,
            checked_only=check,
            updated=False,
            verified=False,
            message="Working tree is dirty. Commit or stash your changes before updating.",
        )

    try:
        _run_git(["fetch", "--prune", remote], cwd=repo_root)
        upstream_ref = f"{remote}/{branch}"
        upstream_rev = _git_output(["rev-parse", upstream_ref], cwd=repo_root)
        ahead_text = _git_output(["rev-list", "--left-right", "--count", f"HEAD...{upstream_ref}"], cwd=repo_root)
        ahead, behind = (int(part) for part in ahead_text.split())
    except Exception as exc:
        return UpdateResult(
            success=False,
            repo_root=repo_root,
            remote=remote,
            branch=branch,
            current_rev=current_rev,
            upstream_rev=None,
            behind=0,
            ahead=0,
            dirty=False,
            checked_only=check,
            updated=False,
            verified=False,
            message=f"Could not inspect update status: {exc}",
        )

    if ahead > 0 and behind > 0:
        return UpdateResult(
            success=False,
            repo_root=repo_root,
            remote=remote,
            branch=branch,
            current_rev=current_rev,
            upstream_rev=upstream_rev,
            behind=behind,
            ahead=ahead,
            dirty=False,
            checked_only=check,
            updated=False,
            verified=False,
            message=(
                f"Local branch has diverged from {remote}/{branch} ({ahead} ahead, {behind} behind). "
                "Refusing to update automatically."
            ),
        )

    if ahead > 0:
        return UpdateResult(
            success=False,
            repo_root=repo_root,
            remote=remote,
            branch=branch,
            current_rev=current_rev,
            upstream_rev=upstream_rev,
            behind=behind,
            ahead=ahead,
            dirty=False,
            checked_only=check,
            updated=False,
            verified=False,
            message=(
                f"Local branch has {ahead} commit(s) ahead of {remote}/{branch}. "
                "Refusing to overwrite local commits."
            ),
        )

    if behind == 0:
        return UpdateResult(
            success=True,
            repo_root=repo_root,
            remote=remote,
            branch=branch,
            current_rev=current_rev,
            upstream_rev=upstream_rev,
            behind=behind,
            ahead=ahead,
            dirty=False,
            checked_only=check,
            updated=False,
            verified=False,
            message="Already up to date.",
        )

    if check:
        return UpdateResult(
            success=True,
            repo_root=repo_root,
            remote=remote,
            branch=branch,
            current_rev=current_rev,
            upstream_rev=upstream_rev,
            behind=behind,
            ahead=ahead,
            dirty=False,
            checked_only=True,
            updated=False,
            verified=False,
            message=f"Update available: {behind} commit(s) behind {remote}/{branch}.",
        )

    pre_update_rev = current_rev
    try:
        _run_git(["pull", "--ff-only", remote, branch], cwd=repo_root)
        updated_rev = _git_output(["rev-parse", "HEAD"], cwd=repo_root)
    except Exception as exc:
        return UpdateResult(
            success=False,
            repo_root=repo_root,
            remote=remote,
            branch=branch,
            current_rev=current_rev,
            upstream_rev=upstream_rev,
            behind=behind,
            ahead=ahead,
            dirty=False,
            checked_only=False,
            updated=False,
            verified=False,
            message=f"Update failed: {exc}",
        )

    verified = False
    if verify:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        verify_proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-o", f"cache_dir={_PYTEST_CACHE_DIR}"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            env=env,
        )
        if verify_proc.returncode != 0:
            rollback_error: str | None = None
            try:
                _run_git(["reset", "--hard", pre_update_rev], cwd=repo_root)
            except Exception as rollback_exc:
                rollback_error = str(rollback_exc)
            stderr = (verify_proc.stderr or "").strip()
            stdout = (verify_proc.stdout or "").strip()
            verify_bits = ["Post-update verification failed. The repo was rolled back to the previous commit."]
            if stdout:
                verify_bits.append(stdout)
            if stderr:
                verify_bits.append(stderr)
            if rollback_error:
                verify_bits.append(f"Rollback error: {rollback_error}")
            return UpdateResult(
                success=False,
                repo_root=repo_root,
                remote=remote,
                branch=branch,
                current_rev=pre_update_rev,
                upstream_rev=upstream_rev,
                behind=behind,
                ahead=ahead,
                dirty=False,
                checked_only=False,
                updated=False,
                verified=False,
                message="\n".join(verify_bits),
            )
        verified = True

    return UpdateResult(
        success=True,
        repo_root=repo_root,
        remote=remote,
        branch=branch,
        current_rev=updated_rev,
        upstream_rev=upstream_rev,
        behind=behind,
        ahead=ahead,
        dirty=False,
        checked_only=False,
        updated=True,
        verified=verified,
        message=f"Updated from {pre_update_rev[:7]} to {updated_rev[:7]} successfully.",
    )


__all__ = ["DEFAULT_BRANCH", "DEFAULT_REMOTE", "UpdateResult", "handle", "render_update_result"]


def render_update_result(result: UpdateResult) -> str:
    return _format_update_report(result)
