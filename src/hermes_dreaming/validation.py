from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Iterable

from .artifact import DreamArtifact, DreamProposal, VALID_MODES, VALID_TARGET_KINDS

SECRET_PATTERNS = [
    re.compile(r"\b(sk-[A-Za-z0-9]{12,}|ghp_[A-Za-z0-9]{8,}|xox[baprs]-[A-Za-z0-9-]{8,}|AIza[0-9A-Za-z_-]{10,})\b"),
    re.compile(r"\b(api[_-]?key|secret|password|token|bearer)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-/.]{8,}", re.IGNORECASE),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
]


def _secret_like(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def _safe_relative_path(path_text: str) -> bool:
    path = PurePosixPath(path_text.replace("\\", "/"))
    if path.is_absolute():
        return False
    return all(part not in {"..", ""} for part in path.parts)


def _proposal_errors(proposal: DreamProposal) -> list[str]:
    errors: list[str] = []
    if proposal.target_kind not in VALID_TARGET_KINDS:
        errors.append(f"proposal {proposal.id} has unsupported target kind {proposal.target_kind!r}")
    if proposal.mode not in VALID_MODES:
        errors.append(f"proposal {proposal.id} has unsupported mode {proposal.mode!r}")
    if not proposal.summary.strip():
        errors.append(f"proposal {proposal.id} is missing a summary")
    if not proposal.provenance:
        errors.append(f"proposal {proposal.id} is missing provenance")
    if not proposal.target_path.strip() or not _safe_relative_path(proposal.target_path):
        errors.append(f"proposal {proposal.id} has an unsafe target path {proposal.target_path!r}")
    if _secret_like(proposal.summary) or _secret_like(proposal.proposed_text):
        errors.append(f"proposal {proposal.id} contains secret-like content")
    if proposal.mode == "jsonl_append":
        try:
            parsed = json.loads(proposal.proposed_text)
        except json.JSONDecodeError:
            errors.append(f"proposal {proposal.id} has malformed JSONL payload")
        else:
            if not isinstance(parsed, dict):
                errors.append(f"proposal {proposal.id} must serialize a JSON object for jsonl_append")
    return errors


def validate_artifact(artifact: DreamArtifact, *, live_root: Path | str) -> list[str]:
    errors: list[str] = []
    live_root = Path(live_root)

    if not artifact.proposals:
        errors.append("artifact contains no proposals")

    seen_targets: dict[str, str] = {}
    for source in artifact.sources:
        if _secret_like(source.content):
            errors.append(f"source {source.path} contains secret-like content")

    for proposal in artifact.proposals:
        errors.extend(_proposal_errors(proposal))
        existing = seen_targets.get(proposal.target_path)
        if existing is not None and existing != proposal.proposed_text:
            errors.append(f"conflicting proposals target the same path {proposal.target_path!r}")
        else:
            seen_targets[proposal.target_path] = proposal.proposed_text

    if not live_root.exists():
        errors.append(f"live root does not exist: {live_root}")

    return errors


def validate_proposals(proposals: Iterable[DreamProposal]) -> list[str]:
    errors: list[str] = []
    seen_targets: dict[str, str] = {}
    for proposal in proposals:
        errors.extend(_proposal_errors(proposal))
        existing = seen_targets.get(proposal.target_path)
        if existing is not None and existing != proposal.proposed_text:
            errors.append(f"conflicting proposals target the same path {proposal.target_path!r}")
        else:
            seen_targets[proposal.target_path] = proposal.proposed_text
    return errors
