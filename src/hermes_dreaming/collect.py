from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator

from .artifact import SourceSnapshot, text_sha256

TEXT_SUFFIXES = {".md", ".txt", ".rst", ".json", ".jsonl", ".yaml", ".yml", ".py"}
SKIP_DIR_NAMES = {".git", ".dreaming", "artifacts", "archive", "discarded", "backups"}


def infer_kind(path: Path) -> str:
    name = path.name.lower()
    parts = {part.lower() for part in path.parts}
    if name == "memory.md":
        return "memory"
    if name == "user.md":
        return "user"
    if "skills" in parts:
        return "skill"
    if name.endswith(".jsonl") and "fact" in name:
        return "fact"
    if "session" in name or "transcript" in name:
        return "session"
    return "source"


def iter_source_files(paths: Iterable[str | Path]) -> Iterator[Path]:
    seen: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            continue
        if path.is_file():
            resolved = path.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield resolved
            continue
        for candidate in sorted(path.rglob("*")):
            if not candidate.is_file():
                continue
            if any(part in SKIP_DIR_NAMES for part in candidate.parts):
                continue
            if candidate.suffix.lower() not in TEXT_SUFFIXES:
                continue
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield resolved


def collect_sources(paths: Iterable[str | Path]) -> list[SourceSnapshot]:
    snapshots: list[SourceSnapshot] = []
    for path in iter_source_files(paths):
        content = path.read_text(encoding="utf-8", errors="replace")
        line_count = content.count("\n") + (1 if content else 0)
        snapshots.append(
            SourceSnapshot(
                path=str(path),
                kind=infer_kind(path),
                content=content,
                sha256=text_sha256(content),
                line_count=line_count,
            )
        )
    snapshots.sort(key=lambda item: item.path)
    return snapshots
