from __future__ import annotations

from difflib import unified_diff
from pathlib import Path

from .apply import preview_proposal_content, resolve_live_target_path
from .artifact import DreamArtifact, DreamProposal


def _legacy_review_output(artifact: DreamArtifact) -> str:
    lines = [artifact.report.rstrip()]
    if artifact.proposals:
        lines.append("")
        for proposal in artifact.proposals:
            lines.append(f"- {proposal.id}: {proposal.target_kind} -> {proposal.target_path} [{proposal.mode}]")
            lines.append(f"  {proposal.summary}")
    return "\n".join(lines).rstrip() + "\n"


def _diff_text(current_text: str, updated_text: str, target_path: str) -> str:
    diff_lines = list(
        unified_diff(
            current_text.splitlines(keepends=True),
            updated_text.splitlines(keepends=True),
            fromfile=f"a/{target_path}",
            tofile=f"b/{target_path}",
            lineterm="",
        )
    )
    return "\n".join(diff_lines)


def _resolved_live_root(artifact: DreamArtifact, live_root: Path | None) -> Path | None:
    if live_root is not None:
        return Path(live_root)
    workspace_root = Path(artifact.workspace_root)
    if workspace_root.exists():
        return workspace_root
    return None


def render_artifact_diff(artifact: DreamArtifact, *, live_root: Path | None = None) -> str:
    resolved_live_root = _resolved_live_root(artifact, live_root)
    if resolved_live_root is None:
        return _legacy_review_output(artifact)

    lines: list[str] = [
        "# Hermes Dreaming Diff",
        "",
        f"- Artifact: `{artifact.artifact_id}`",
        f"- Status: `{artifact.status}`",
        f"- Live root: `{resolved_live_root}`",
        "",
    ]

    if not artifact.proposals:
        lines.extend(["## Proposals", "", "- None", ""])
        return "\n".join(lines).rstrip() + "\n"

    for proposal in artifact.proposals:
        target = resolve_live_target_path(resolved_live_root, proposal)
        current_text = target.read_text(encoding="utf-8") if target.exists() else ""
        updated_text = preview_proposal_content(current_text, proposal)
        provenance = ", ".join(proposal.provenance) if proposal.provenance else "none"
        lines.extend(
            [
                f"## Proposal {proposal.id}",
                f"- target: {proposal.target_kind} -> {proposal.target_path}",
                f"- mode: {proposal.mode}",
                f"- summary: {proposal.summary}",
                f"- provenance: {provenance}",
                f"- live target: `{target}`",
            ]
        )
        diff_text = _diff_text(current_text, updated_text, proposal.target_path)
        if diff_text:
            lines.append(diff_text)
        else:
            lines.append("- no content changes")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
