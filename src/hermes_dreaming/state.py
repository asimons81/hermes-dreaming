from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _default_state_root() -> Path:
    configured = os.environ.get("HERMES_DREAMING_STATE_ROOT")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".hermes" / "dreaming"


STATE_ROOT = _default_state_root()
STATE_JSON = STATE_ROOT / "state.json"
RUN_LEDGER_JSONL = STATE_ROOT / "runs.jsonl"
DREAMS_MD_PATH = STATE_ROOT / "DREAMS.md"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _resolve_path(path: Path | None, default: Path) -> Path:
    return Path(path) if path is not None else default


def read(*, state_path: Path | None = None) -> dict[str, Any]:
    path = _resolve_path(state_path, STATE_JSON)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write(data: dict[str, Any], *, state_path: Path | None = None) -> None:
    path = _resolve_path(state_path, STATE_JSON)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def record_session_pointer(session_id: str, *, state_path: Path | None = None, limit: int = 50) -> None:
    state = read(state_path=state_path)
    pointers = list(state.get("recent_session_ids", []))
    if session_id not in pointers:
        pointers.append(session_id)
    state["recent_session_ids"] = pointers[-limit:]
    write(state, state_path=state_path)


def read_run_ledger(*, ledger_path: Path | None = None) -> list[dict[str, Any]]:
    path = _resolve_path(ledger_path, RUN_LEDGER_JSONL)
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        entry = line.strip()
        if not entry:
            continue
        try:
            record = json.loads(entry)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _normalize_run_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    normalized["command"] = str(normalized.get("command", "unknown"))
    normalized["timestamp"] = str(normalized.get("timestamp") or _now_iso())
    if "success" in normalized:
        normalized["success"] = bool(normalized["success"])
    else:
        outcome = str(normalized.get("outcome", "")).lower()
        normalized["success"] = outcome in {"success", "succeeded", "ok", "passed", "done"}
    if "summary" in normalized and normalized["summary"] is not None:
        normalized["summary"] = str(normalized["summary"])
    return normalized


def record_run(
    record: dict[str, Any],
    *,
    state_path: Path | None = None,
    ledger_path: Path | None = None,
    diary_path: Path | None = None,
) -> dict[str, Any]:
    state_path = _resolve_path(state_path, STATE_JSON)
    ledger_path = _resolve_path(ledger_path, RUN_LEDGER_JSONL)
    diary_path = _resolve_path(diary_path, DREAMS_MD_PATH)

    normalized = _normalize_run_record(record)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(normalized, ensure_ascii=False, sort_keys=True) + "\n")

    runs = read_run_ledger(ledger_path=ledger_path)
    successful_runs = [run for run in runs if bool(run.get("success"))]
    state = read(state_path=state_path)
    state.update(
        {
            "last_run": runs[-1] if runs else normalized,
            "last_successful_run": successful_runs[-1] if successful_runs else None,
            "run_count": len(runs),
            "successful_run_count": len(successful_runs),
            "run_ledger_path": str(ledger_path),
            "dreams_md_path": str(diary_path),
        }
    )
    write(state, state_path=state_path)

    from .dreams_md import write_dreams_md

    write_dreams_md(runs, diary_path=diary_path)
    return normalized
