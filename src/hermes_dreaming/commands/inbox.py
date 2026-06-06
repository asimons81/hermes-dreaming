from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
import json

from ..analyze import list_artifacts
from ..artifact import DreamArtifact, DreamProposal, proposal_state
from ..triage import (
    PRIORITY_ORDER,
    RISK_ORDER,
    aggregate_policy_flags,
    highest_level,
    proposal_detail_lines,
    proposal_view,
    sorted_proposals,
)


@dataclass(slots=True)
class InboxProposalView:
    id: str
    state: str
    target_kind: str
    target_path: str
    summary: str
    confidence: float
    risk: str
    priority: str
    reason: str
    source_quote: str
    policy_flags: list[str]
    provenance: list[str]


@dataclass(slots=True)
class InboxRow:
    artifact_id: str
    artifact_dir: str
    created_at: str
    age: str
    age_seconds: int | None
    artifact_status: str
    inbox_state: str
    proposal_counts: dict[str, int]
    target_kinds: dict[str, int]
    highest_risk: str
    highest_priority: str
    policy_flags: list[str]
    source_summary: str
    top_reason: str
    next_command: str
    proposals: list[InboxProposalView]


@dataclass(slots=True)
class InboxResult:
    artifact_root: str
    total_artifacts: int
    rows: list[InboxRow]
    skipped_corrupt: int = 0


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_age(created_at: str) -> tuple[str, int | None]:
    parsed = _parse_iso8601(created_at)
    if parsed is None:
        return "unknown age", None
    now = datetime.now(timezone.utc)
    delta = max(0, int((now - parsed).total_seconds()))
    minutes = delta // 60
    hours = minutes // 60
    days = hours // 24
    if days:
        return f"{days}d {hours % 24}h old", delta
    if hours:
        return f"{hours}h {minutes % 60}m old", delta
    if minutes:
        return f"{minutes}m old", delta
    return "just now", delta


def _state_counts(artifact: DreamArtifact) -> dict[str, int]:
    counts: dict[str, int] = {}
    for proposal in artifact.proposals:
        state = proposal_state(proposal)
        counts[state] = counts.get(state, 0) + 1
    return dict(sorted(counts.items()))


def _inbox_state(artifact: DreamArtifact) -> str:
    if artifact.status in {"applied", "discarded", "archived", "invalid"}:
        return artifact.status
    counts = _state_counts(artifact)
    active = {state for state in ("pending", "approved", "rejected") if counts.get(state, 0)}
    if not active:
        return artifact.status
    if len(active) > 1:
        return "mixed"
    only = next(iter(active))
    return "staged" if only == "pending" else only


def _source_summary(artifact: DreamArtifact) -> str:
    if artifact.source_roots:
        return ", ".join(Path(item).name or str(item) for item in artifact.source_roots[:3])
    if artifact.sources:
        return ", ".join(Path(source.path).name or source.path for source in artifact.sources[:3])
    return "none"


def _top_reason(artifact: DreamArtifact) -> str:
    for proposal in sorted_proposals(artifact.proposals):
        reason = str(getattr(proposal, "reason", "") or "").strip()
        if reason:
            return reason
        if proposal.summary.strip():
            return proposal.summary.strip()
    return "none"


def _next_command(artifact_dir: Path, state: str, artifact: DreamArtifact) -> str:
    artifact_text = shlex_quote(str(artifact_dir))
    live_root_text = shlex_quote(str(Path(artifact.workspace_root)))
    counts = _state_counts(artifact)
    if state in {"staged", "mixed"} or counts.get("pending", 0):
        return f"dreaming summarize {artifact_text}"
    if state == "approved" or counts.get("approved", 0):
        return f"dreaming apply {artifact_text} --live-root {live_root_text} --backup-root <backup-root>"
    if state == "invalid":
        return f"dreaming validate {artifact_text} --live-root {live_root_text}"
    return f"dreaming review --open {artifact_text}"


def shlex_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


def _proposal_views(artifact: DreamArtifact) -> list[InboxProposalView]:
    views: list[InboxProposalView] = []
    for proposal in sorted_proposals(artifact.proposals):
        view = proposal_view(proposal)
        views.append(
            InboxProposalView(
                id=view.id,
                state=view.state,
                target_kind=view.target_kind,
                target_path=view.target_path,
                summary=view.summary,
                confidence=view.confidence,
                risk=view.risk,
                priority=view.priority,
                reason=view.reason,
                source_quote=view.source_quote,
                policy_flags=list(view.policy_flags),
                provenance=list(view.provenance),
            )
        )
    return views


def build_inbox(
    artifact_root: Path,
    *,
    state_filter: set[str] | None = None,
    priority_filter: set[str] | None = None,
    apply_ready: bool = False,
    limit: int | None = None,
) -> InboxResult:
    artifact_root = Path(artifact_root)
    artifacts = list_artifacts(artifact_root)
    rows: list[InboxRow] = []
    for artifact in artifacts:
        artifact_dir = artifact_root / artifact.artifact_id
        state = _inbox_state(artifact)
        highest_priority = highest_level(artifact.proposals, "priority", order=PRIORITY_ORDER, default="normal")
        highest_risk = highest_level(artifact.proposals, "risk", order=RISK_ORDER, default="low")
        if state_filter and state not in state_filter:
            continue
        if priority_filter and highest_priority not in priority_filter:
            continue
        if apply_ready and not _is_apply_ready(artifact):
            continue
        counts = _state_counts(artifact)
        target_kinds: dict[str, int] = {}
        for proposal in artifact.proposals:
            target_kinds[proposal.target_kind] = target_kinds.get(proposal.target_kind, 0) + 1
        age, age_seconds = _format_age(artifact.created_at)
        rows.append(
            InboxRow(
                artifact_id=artifact.artifact_id,
                artifact_dir=str(artifact_dir),
                created_at=artifact.created_at,
                age=age,
                age_seconds=age_seconds,
                artifact_status=artifact.status,
                inbox_state=state,
                proposal_counts=counts,
                target_kinds=dict(sorted(target_kinds.items())),
                highest_risk=highest_risk,
                highest_priority=highest_priority,
                policy_flags=aggregate_policy_flags(artifact.proposals),
                source_summary=_source_summary(artifact),
                top_reason=_top_reason(artifact),
                next_command=_next_command(artifact_dir, state, artifact),
                proposals=_proposal_views(artifact),
            )
        )
    rows = sorted(
        rows,
        key=lambda row: (
            -PRIORITY_ORDER.get(str(row.highest_priority or "normal").lower(), 0),
            -RISK_ORDER.get(str(row.highest_risk or "low").lower(), 0),
            str(row.created_at),
        ),
    )
    if limit is not None:
        rows = rows[: max(0, limit)]
    return InboxResult(artifact_root=str(artifact_root), total_artifacts=len(artifacts), rows=rows)


def _is_apply_ready(artifact: DreamArtifact) -> bool:
    """A row is apply-ready when its status is non-terminal and no pending proposals remain.

    Statuses considered apply-capable: staged, approved, applied.
    Every non-rejected proposal must be approved (or already applied).
    """
    if artifact.status not in {"staged", "approved", "applied"}:
        return False
    for proposal in artifact.proposals:
        if proposal.rejected:
            continue
        if not proposal.approved and not proposal.applied:
            return False
    return True


def parse_filter(value: str | None) -> set[str] | None:
    if value is None or not value.strip():
        return None
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def render_inbox(result: InboxResult) -> str:
    lines = [
        "# Hermes Dreaming inbox",
        "",
        f"- Artifact root: `{result.artifact_root}`",
        f"- Artifacts scanned: `{result.total_artifacts}`",
        f"- Rows shown: `{len(result.rows)}`",
    ]
    if result.skipped_corrupt:
        lines.append(f"- Corrupt artifacts skipped: `{result.skipped_corrupt}`")
    lines.extend(["", "## Queue", ""])
    if not result.rows:
        lines.append("- No matching artifacts.")
        return "\n".join(lines).rstrip() + "\n"
    for row in result.rows:
        counts = ", ".join(f"{k}={v}" for k, v in row.proposal_counts.items()) if row.proposal_counts else "none"
        kinds = ", ".join(f"{k}={v}" for k, v in row.target_kinds.items()) if row.target_kinds else "none"
        flags = ", ".join(row.policy_flags) if row.policy_flags else "none"
        lines.extend(
            [
                f"- `{row.artifact_id}` [{row.inbox_state}] ({row.age})",
                f"  - created: `{row.created_at}`",
                f"  - artifact dir: `{row.artifact_dir}`",
                f"  - proposals: {counts}",
                f"  - target kinds: {kinds}",
                f"  - risk/priority: `{row.highest_risk}` / `{row.highest_priority}`",
                f"  - policy flags: {flags}",
                f"  - source: {row.source_summary}",
                f"  - reason: {row.top_reason}",
                f"  - next: `{row.next_command}`",
            ]
        )
        if row.proposals:
            lines.append("  - top proposal:")
            lines.extend(f"    {line.lstrip()}" for line in proposal_detail_lines(_to_proposal(row.proposals[0])))
    return "\n".join(lines).rstrip() + "\n"


def _to_proposal(view: InboxProposalView) -> DreamProposal:
    return DreamProposal(
        id=view.id,
        target_kind=view.target_kind,
        target_path=view.target_path,
        mode="append_text",
        summary=view.summary,
        provenance=list(view.provenance),
        proposed_text=view.source_quote or view.summary,
        approved=view.state == "approved",
        confidence=view.confidence,
        risk=view.risk,
        priority=view.priority,
        reason=view.reason,
        source_quote=view.source_quote,
        policy_flags=list(view.policy_flags),
        rejected=view.state == "rejected",
        applied=view.state == "applied",
    )


def render_inbox_json(result: InboxResult) -> str:
    return json.dumps(asdict(result), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
