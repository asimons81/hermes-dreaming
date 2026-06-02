from __future__ import annotations

import textwrap
from pathlib import Path

try:
    from hermes_constants import get_hermes_home  # type: ignore
except Exception:  # pragma: no cover - fallback for direct source inspection
    def get_hermes_home() -> Path:
        return Path.home() / ".hermes"

JOB_NAME = "hermes-dreaming"
DEFAULT_SCHEDULE = "0 3 * * *"
SCRIPT_NAME = "hermes_dreaming_status_digest.py"
_PROMPT = "Hermes Dreaming daily digest"


_DIGEST_SCRIPT_TEMPLATE = textwrap.dedent(
    '''
    #!/usr/bin/env python3
    from __future__ import annotations

    import json
    import os
    import subprocess
    from pathlib import Path

    REPO_ROOT = Path(__REPO_ROOT__)


    def _read_json(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}


    def _read_jsonl(path: Path) -> list[dict]:
        rows: list[dict] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                entry = line.strip()
                if not entry:
                    continue
                try:
                    parsed = json.loads(entry)
                except Exception:
                    continue
                if isinstance(parsed, dict):
                    rows.append(parsed)
        except Exception:
            return []
        return rows


    def _git_status(repo_root: Path) -> list[str]:
        try:
            result = subprocess.run(
                ["git", "-C", str(repo_root), "status", "--short", "--branch"],
                capture_output=True,
                text=True,
                check=False,
            )
        except Exception as exc:
            return [f"git unavailable: {exc}"]

        output = (result.stdout or "").strip()
        if not output:
            return ["clean"]
        return output.splitlines()


    def _artifact_summary(artifact_root: Path) -> tuple[dict[str, int], list[str]]:
        counts: dict[str, int] = {}
        latest: list[tuple[float, str]] = []
        if not artifact_root.exists():
            return counts, []

        for manifest in sorted(artifact_root.glob("*/manifest.json")):
            try:
                data = json.loads(manifest.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            status = str(data.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
            artifact_id = str(data.get("artifact_id") or manifest.parent.name)
            try:
                stamp = manifest.stat().st_mtime
            except OSError:
                stamp = 0.0
            latest.append((stamp, f"{artifact_id} [{status}]"))

        latest.sort(key=lambda item: item[0], reverse=True)
        return counts, [item[1] for item in latest[:3]]


    def _format_run(record: dict | None) -> str:
        if not record:
            return "none"
        timestamp = str(record.get("timestamp", "unknown time"))
        command = str(record.get("command", "unknown"))
        outcome = "success" if record.get("success") else "failure"
        parts = [f"{timestamp} — {command} ({outcome})"]
        artifact_id = record.get("artifact_id")
        if artifact_id:
            parts.append(f"artifact={artifact_id}")
        artifact_status = record.get("artifact_status")
        if artifact_status:
            parts.append(f"status={artifact_status}")
        summary = record.get("summary")
        if summary:
            parts.append(str(summary))
        return " | ".join(parts)


    def main() -> int:
        state_root = Path(
            os.environ.get("HERMES_DREAMING_STATE_ROOT", str(Path.home() / ".hermes" / "dreaming"))
        )
        artifact_root = REPO_ROOT / ".dreaming" / "artifacts"
        state = _read_json(state_root / "state.json")
        runs = _read_jsonl(state_root / "runs.jsonl")
        git_lines = _git_status(REPO_ROOT)
        artifact_counts, latest_artifacts = _artifact_summary(artifact_root)

        successful_runs = state.get("successful_run_count")
        if not isinstance(successful_runs, int):
            successful_runs = sum(1 for record in runs if record.get("success"))
        run_count = state.get("run_count")
        if not isinstance(run_count, int):
            run_count = len(runs)

        last_run = state.get("last_run") if isinstance(state.get("last_run"), dict) else None
        if last_run is None and runs:
            last_run = runs[-1]
        last_successful_run = state.get("last_successful_run") if isinstance(state.get("last_successful_run"), dict) else None
        if last_successful_run is None:
            for record in reversed(runs):
                if record.get("success"):
                    last_successful_run = record
                    break

        print("## Hermes Dreaming daily digest")
        print("")
        print(f"- Repo: `{REPO_ROOT}`")
        print(f"- Artifact root: `{artifact_root}`")
        print(f"- State root: `{state_root}`")
        print("")
        print("## Git status")
        print("")
        for line in git_lines:
            print(f"- `{line}`")
        print("")
        print("## Dreaming runtime")
        print("")
        print(f"- Runs: `{run_count}` total, `{successful_runs}` successful")
        print(f"- Last run: `{_format_run(last_run)}`")
        print(f"- Last successful run: `{_format_run(last_successful_run)}`")
        print(f"- Ledger bytes: `{(state_root / 'runs.jsonl').stat().st_size if (state_root / 'runs.jsonl').exists() else 0}`")
        print(f"- Diary bytes: `{(state_root / 'DREAMS.md').stat().st_size if (state_root / 'DREAMS.md').exists() else 0}`")
        print("")
        print("## Staged artifacts")
        print("")
        if not artifact_root.exists():
            print("- No `.dreaming/artifacts` directory under the repo root.")
        elif not artifact_counts:
            print("- No artifacts staged yet.")
        else:
            for status, count in sorted(artifact_counts.items()):
                print(f"- {status}: `{count}`")
            if latest_artifacts:
                print("")
                print("### Latest artifacts")
                print("")
                for item in latest_artifacts:
                    print(f"- `{item}`")
        return 0


    if __name__ == "__main__":
        raise SystemExit(main())
    '''
).lstrip()


def _repo_root() -> Path:
    """Best-effort repo root lookup for the installed plugin checkout."""

    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists() and (parent / "plugin.yaml").exists():
            return parent
    return here.parents[3]


def _script_path() -> Path:
    return Path(get_hermes_home()) / "scripts" / SCRIPT_NAME


def _ensure_digest_script() -> Path:
    script_path = _script_path()
    script_path.parent.mkdir(parents=True, exist_ok=True)
    current = script_path.read_text(encoding="utf-8") if script_path.exists() else None
    script_text = _DIGEST_SCRIPT_TEMPLATE.replace("__REPO_ROOT__", repr(str(_repo_root())))
    if current != script_text:
        script_path.write_text(script_text, encoding="utf-8")
        try:
            script_path.chmod(0o755)
        except OSError:
            pass
    return script_path


def _find_existing(list_jobs_fn) -> dict | None:
    try:
        for job in list_jobs_fn(include_disabled=True):
            if job.get("name") == JOB_NAME:
                return job
    except Exception:
        return None
    return None


def _desired_job_fields(schedule: str) -> dict:
    return {
        "prompt": _PROMPT,
        "schedule": schedule,
        "name": JOB_NAME,
        "deliver": "local",
        "script": SCRIPT_NAME,
        "no_agent": True,
        "workdir": str(_repo_root()),
    }


def _job_matches(job: dict, desired: dict) -> bool:
    return all(job.get(key) == value for key, value in desired.items())


def _render_job_block(header: str, job: dict, schedule_display: str) -> str:
    return (
        "## hermes dreaming install-cron\n\n"
        f"**{header}.**\n\n"
        f"- Job ID:    `{job['id']}`\n"
        f"- Name:      `{JOB_NAME}`\n"
        f"- Schedule:  {schedule_display}\n"
        f"- Next run:  {job.get('next_run_at', 'unknown')}\n"
        f"- Mode:      no-agent digest script\n"
        f"- Script:    `{SCRIPT_NAME}`\n"
        f"- Workdir:   `{_repo_root()}`\n\n"
        "Each night Hermes will run a deterministic status digest, so you get an actual report instead of a polite little tombstone."
    )


def handle(schedule: str | None = None) -> str:
    """Register or refresh the nightly Hermes Dreaming digest cron job."""

    try:
        from cron.jobs import create_job, list_jobs, update_job
    except ImportError:
        return (
            "## hermes dreaming install-cron\n\n"
            "**Error:** Hermes cron module not available in this environment.\n\n"
            "Start Hermes in an environment that exposes `cron.jobs`, then retry."
        )

    schedule = (schedule or DEFAULT_SCHEDULE).strip()
    _ensure_digest_script()
    desired = _desired_job_fields(schedule)

    existing = _find_existing(list_jobs)
    if existing:
        if _job_matches(existing, desired):
            schedule_display = existing.get("schedule_display", existing.get("schedule", "?"))
            return _render_job_block("Already installed", existing, schedule_display)

        updated = update_job(existing["id"], desired)
        if not updated:
            return (
                "## hermes dreaming install-cron\n\n"
                f"**Error updating cron job `{existing['id']}`.**\n\n"
                "The job exists, but Hermes could not refresh it. Check the cron registry and retry."
            )
        schedule_display = updated.get("schedule_display", updated.get("schedule", "?"))
        return _render_job_block("Cron job updated", updated, schedule_display)

    try:
        job = create_job(**desired)
    except Exception as exc:
        return (
            "## hermes dreaming install-cron\n\n"
            f"**Error creating cron job:** {exc}\n\n"
            f"Check that the schedule expression `{schedule}` is valid "
            "(for example, `0 3 * * *` for nightly at 03:00)."
        )

    schedule_display = job.get("schedule_display", schedule)
    return _render_job_block("Cron job registered", job, schedule_display)
