from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(autouse=True)
def isolate_dreaming_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests from writing the operator's real ~/.hermes/dreaming ledger."""

    state_root = tmp_path / "hermes-dreaming-state"
    monkeypatch.setattr("hermes_dreaming.state.STATE_ROOT", state_root)
    monkeypatch.setattr("hermes_dreaming.state.STATE_JSON", state_root / "state.json")
    monkeypatch.setattr("hermes_dreaming.state.RUN_LEDGER_JSONL", state_root / "runs.jsonl")
    monkeypatch.setattr("hermes_dreaming.state.DREAMS_MD_PATH", state_root / "DREAMS.md")
