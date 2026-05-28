from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_state_root_can_be_overridden_with_environment(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    state_root = tmp_path / "dreaming-state"
    code = """
from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd() / 'src'))
from hermes_dreaming import state
print(state.STATE_ROOT)
print(state.STATE_JSON)
"""
    env = dict(os.environ)
    env["HERMES_DREAMING_STATE_ROOT"] = str(state_root)

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo_root,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )

    lines = result.stdout.splitlines()
    assert lines[0] == str(state_root)
    assert lines[1] == str(state_root / "state.json")
