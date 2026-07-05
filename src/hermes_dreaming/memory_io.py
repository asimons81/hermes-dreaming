from __future__ import annotations

"""
Read, parse, preview, and write Hermes durable memory files.

These helpers are intentionally small and deterministic so the scoring layer
can gate operations before any live mutation occurs.
"""

from dataclasses import dataclass
import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import NamedTuple

MEMORY_MD = Path.home() / ".hermes" / "dreaming" / "memory.md"
USER_MD = Path.home() / ".hermes" / "dreaming" / "user.md"
MEMORY_MD_LIMIT = 4000
USER_MD_LIMIT = 4000
BACKUPS_DIR = Path.home() / ".hermes" / "dreaming" / "backups"


class MemoryFile(NamedTuple):
    target: str
    path: Path
    raw: str
    entries: list[str]
    char_count: int
    char_limit: int

    @property
    def free(self) -> int:
        return max(0, self.char_limit - self.char_count)

    @property
    def usage_pct(self) -> float:
        return round(100 * self.char_count / self.char_limit, 1)

    @property
    def near_capacity(self) -> bool:
        return self.usage_pct >= 80

    def summary_line(self) -> str:
        return (
            f"{self.target.upper()}.md  "
            f"{self.char_count}/{self.char_limit} chars "
            f"({self.usage_pct}%)  —  {len(self.entries)} entries"
        )


@dataclass
class MutationResult:
    ok: bool
    new_text: str = ""
    char_delta: int = 0
    error: str = ""


def _parse_entries(text: str) -> list[str]:
    """Extract bullet-list lines from a memory file."""
    entries: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("-") or stripped == "-":
            continue
        entries.append(stripped)
    return entries


def _target_info(target: str) -> tuple[Path, int]:
    if target == "memory":
        return MEMORY_MD, MEMORY_MD_LIMIT
    if target == "user":
        return USER_MD, USER_MD_LIMIT
    raise ValueError(f"Unknown target: {target!r}. Use 'memory' or 'user'.")


def _alternate_name(name: str) -> str:
    stem, dot, suffix = name.partition(".")
    if not dot:
        return stem.lower() if stem.isupper() else stem.upper()
    flipped_stem = stem.lower() if stem.isupper() else stem.upper()
    return f"{flipped_stem}.{suffix}"


def _resolve_existing_path(path: Path) -> Path:
    alternate = path.with_name(_alternate_name(path.name))
    try:
        exact_names = {child.name for child in path.parent.iterdir()}
    except OSError:
        exact_names = set()
    if alternate.name in exact_names:
        return alternate
    if path.name in exact_names:
        return path
    if path.exists():
        return path
    if alternate.exists():
        return alternate
    return path


def resolve_target_path(root: Path, target: str) -> Path:
    """Resolve a live target under *root*, preferring uppercase MEMORY/USER files."""
    if target == "memory":
        candidates = [root / "MEMORY.md", root / "memory.md"]
    elif target == "user":
        candidates = [root / "USER.md", root / "user.md"]
    else:
        raise ValueError(f"Unknown target: {target!r}. Use 'memory' or 'user'.")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def read(target: str) -> MemoryFile:
    """Read and parse a memory file. target is 'memory' or 'user'."""
    path, limit = _target_info(target)
    path = _resolve_existing_path(path)
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    return MemoryFile(
        target=target,
        path=path,
        raw=raw,
        entries=_parse_entries(raw),
        char_count=len(raw),
        char_limit=limit,
    )


def read_both() -> dict[str, MemoryFile]:
    """Return {'memory': MemoryFile, 'user': MemoryFile}."""
    return {"memory": read("memory"), "user": read("user")}


def memory_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def op_hash(op: str, target: str, old_text: str | None, new_text: str | None) -> str:
    sig = f"{op}:{target}:{old_text or ''}:{new_text or ''}"
    return memory_sha256(sig)


def _write_atomic(path: Path, content: str) -> None:
    """Write content to path via a temp file + os.replace for atomicity."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".drm_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _line_body(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("- "):
        return stripped[2:].strip()
    return stripped


def _resolve_line(lines: list[str], old_text: str, path: Path) -> tuple[int | None, str]:
    """Resolve an exact line match and report partial/ambiguous anchors clearly."""
    anchor = old_text.strip()
    if not anchor:
        return None, f"old_text is required for {path.name}"

    exact_matches = [
        i for i, line in enumerate(lines)
        if line.strip() == anchor or _line_body(line) == anchor
    ]
    if len(exact_matches) == 1:
        return exact_matches[0], ""
    if len(exact_matches) > 1:
        return None, f"old_text is ambiguous in {path.name}: {old_text!r}"

    partial_matches = [i for i, line in enumerate(lines) if anchor in line.strip()]
    if partial_matches:
        return None, (
            f"old_text must exactly match one entry in {path.name}; "
            f"partial anchor matched {len(partial_matches)} line(s): {old_text!r}"
        )
    return None, f"old_text not found in {path.name}: {old_text!r}"


def _line_text(text: str) -> str:
    return text.strip().rstrip("\r\n")


def preview_add(raw: str, new_text: str) -> MutationResult:
    """Return the add result without writing it."""
    entry = _line_text(new_text)
    if not entry:
        return MutationResult(ok=False, error="new_text is required for add")
    if entry in _parse_entries(raw):
        return MutationResult(ok=True, new_text=raw, char_delta=0)
    separator = "\n" if raw and not raw.endswith("\n") else ""
    updated = raw + separator + entry + "\n"
    return MutationResult(ok=True, new_text=updated, char_delta=len(updated) - len(raw))


def preview_replace(raw: str, path: Path, old_text: str, new_text: str) -> MutationResult:
    """Return the replace result without writing it."""
    replacement = _line_text(new_text)
    if not replacement:
        return MutationResult(ok=False, error="new_text is required for replace")

    lines = raw.splitlines(keepends=True)
    stripped_lines = [line.rstrip("\r\n") for line in lines]
    idx, error = _resolve_line(stripped_lines, old_text, path)
    if idx is None:
        if replacement in stripped_lines:
            return MutationResult(ok=True, new_text=raw, char_delta=0)
        return MutationResult(ok=False, error=error)
    if stripped_lines[idx] == replacement:
        return MutationResult(ok=True, new_text=raw, char_delta=0)
    lines[idx] = f"{replacement}\n"
    updated = "".join(lines)
    return MutationResult(ok=True, new_text=updated, char_delta=len(updated) - len(raw))


def preview_remove(raw: str, path: Path, old_text: str) -> MutationResult:
    """Return the remove result without writing it."""
    lines = raw.splitlines(keepends=True)
    stripped_lines = [line.rstrip("\r\n") for line in lines]
    idx, error = _resolve_line(stripped_lines, old_text, path)
    if idx is None:
        anchor = _line_text(old_text)
        if anchor and anchor not in stripped_lines and anchor not in raw:
            return MutationResult(ok=True, new_text=raw, char_delta=0)
        return MutationResult(ok=False, error=error)
    removed_len = len(lines[idx])
    del lines[idx]
    updated = "".join(lines)
    return MutationResult(ok=True, new_text=updated, char_delta=-removed_len)


def apply_add(path: Path, new_text: str) -> MutationResult:
    """Append *new_text* as a new bullet line."""
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    result = preview_add(raw, new_text)
    if result.ok and result.new_text != raw:
        _write_atomic(path, result.new_text)
    return result


def apply_replace(path: Path, old_text: str, new_text: str) -> MutationResult:
    """Replace the single entry exactly matching *old_text* with *new_text*."""
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    result = preview_replace(raw, path, old_text, new_text)
    if result.ok and result.new_text != raw:
        _write_atomic(path, result.new_text)
    return result


def apply_remove(path: Path, old_text: str) -> MutationResult:
    """Remove the single entry exactly matching *old_text*."""
    raw = path.read_text(encoding="utf-8") if path.exists() else ""
    result = preview_remove(raw, path, old_text)
    if result.ok and result.new_text != raw:
        _write_atomic(path, result.new_text)
    return result


def backup_target(path: Path, backup_root: Path, *, target: str) -> Path:
    """Copy a live memory file into the backup tree and return the backup path.

    Always creates a fresh backup — never returns a stale snapshot from a
    previous run.  Rollback on failure must restore the immediately-preceding
    state, not the state from yesterday."""
    backup_path = backup_root / target / path.name
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, backup_path)
    else:
        backup_path.write_text("", encoding="utf-8")
    return backup_path


def restore_target(path: Path, backup_root: Path, *, target: str) -> Path:
    """Restore a live memory file from its backup snapshot."""
    backup_path = backup_root / target / path.name
    if not backup_path.exists():
        raise FileNotFoundError(f"backup not found for {path.name}: {backup_path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup_path, path)
    return backup_path


def format_for_prompt(mf: MemoryFile) -> str:
    """Render a MemoryFile for inclusion in an orchestration prompt."""
    header = (
        f"### {mf.target.upper()}.md  "
        f"[{mf.char_count}/{mf.char_limit} chars, {mf.usage_pct}% used"
        + (", NEAR CAPACITY" if mf.near_capacity else "")
        + "]\n"
    )
    if not mf.raw.strip():
        return header + "(empty)\n"
    return header + mf.raw + "\n"
