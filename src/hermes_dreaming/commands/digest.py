from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import shlex
from typing import Any, Iterable

from .. import state as state_module
from ..analyze import list_artifacts
from ..artifact import DreamArtifact, DreamProposal, load_artifact, proposal_state
from .inbox import build_inbox, render_inbox
from ..triage import PRIORITY_ORDER, RISK_ORDER, proposal_detail_lines, sorted_proposals


TARGET_KIND_WEIGHT = {
    "user": 40,
    "skill": 30,
    "memory": 20,
    "fact": 10,
}

CONFIDENCE_WEIGHTS = (
    (0.90, 20),
    (0.80, 15),
    (0.70, 8),
)

STOPWORDS = {
    "a",
    "an",
    "and",
    "apply",
    "approve",
    "approved",
    "artifact",
    "change",
    "changes",
    "digest",
    "fix",
    "note",
    "notes",
    "proposal",
    "proposals",
    "review",
    "reviews",
    "staged",
    "summary",
    "update",
    "updates",
    "user",
    "skill",
    "memory",
    "fact",
    "the",
    "to",
    "with",
    "for",
    "of",
    "in",
    "on",
}


@dataclass(slots=True)
class DigestProposalView:
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
    score: int
    approve_command: str
    reject_command: str
    theme_key: str
    rejection_reason: str | None = None


@dataclass(slots=True)
class DigestWeeklyRollup:
    accepted_themes: list[tuple[str, int]]
    rejected_themes: list[tuple[str, int]]
    recurring_themes: list[tuple[str, int]]
    decision_patterns: list[str]
    watchlist: list[str]


@dataclass(slots=True)
class DigestResult:
    artifact: DreamArtifact
    artifact_root: Path
    state_root: Path
    previous_artifact_id: str | None
    priority_score: int
    proposal_views: list[DigestProposalView]
    delta_lines: list[str]
    next_step: str
    weekly_rollup: DigestWeeklyRollup | None


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


def _format_iso8601(value: datetime | None) -> str:
    if value is None:
        return "unknown time"
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_quote(value: str | Path) -> str:
    return shlex.quote(str(value))


def _normalize_theme_label(text: str) -> str:
    tokens = re.findall(r"[A-Za-z0-9']+", text.lower())
    meaningful = [token for token in tokens if token not in STOPWORDS]
    if not meaningful:
        return "general"
    return " ".join(meaningful[:4])


def _proposal_theme_key(proposal: DreamProposal) -> str:
    base = proposal.summary.strip() or proposal.target_path.strip() or proposal.target_kind
    label = _normalize_theme_label(base)
    return f"{proposal.target_kind}: {label}"


def _confidence_weight(confidence: float) -> int:
    for threshold, weight in CONFIDENCE_WEIGHTS:
        if confidence >= threshold:
            return weight
    return 0


def _artifact_source_key(artifact: DreamArtifact) -> tuple[str, ...]:
    if artifact.sources:
        return tuple(sorted(source.sha256 for source in artifact.sources))
    if artifact.source_roots:
        return tuple(sorted(artifact.source_roots))
    return (artifact.artifact_id,)


def _proposal_conflicts(proposals: list[DreamProposal]) -> set[str]:
    counts = Counter(proposal.target_path for proposal in proposals)
    return {target_path for target_path, count in counts.items() if count > 1}


def _evidence_weight(proposal: DreamProposal, previous_theme_keys: set[str]) -> int:
    if proposal.snippet.strip():
        return 10
    if len(proposal.provenance) >= 2:
        return 8
    if len(proposal.provenance) == 1:
        return 5
    if _proposal_theme_key(proposal) in previous_theme_keys:
        return 5
    return 0


def _recurrence_bonus(proposal: DreamProposal, previous_theme_keys: set[str], theme_counts: Counter[str]) -> int:
    theme_key = _proposal_theme_key(proposal)
    if theme_key in previous_theme_keys:
        return 10
    if theme_counts[theme_key] >= 2:
        return 5
    return 0


def _conflict_penalty(proposal: DreamProposal, conflicting_paths: set[str]) -> int:
    penalty = 0
    if proposal.target_path in conflicting_paths:
        penalty += 25
    if len(proposal.summary.strip()) < 12:
        penalty += 10
    if proposal.confidence < 0.70:
        penalty += 5
    if not proposal.provenance:
        penalty += 5
    return penalty


def _proposal_score(proposal: DreamProposal, *, previous_theme_keys: set[str], theme_counts: Counter[str], conflicting_paths: set[str]) -> int:
    score = TARGET_KIND_WEIGHT.get(proposal.target_kind, 0)
    score += _confidence_weight(proposal.confidence)
    score += _evidence_weight(proposal, previous_theme_keys)
    score += _recurrence_bonus(proposal, previous_theme_keys, theme_counts)
    score -= _conflict_penalty(proposal, conflicting_paths)
    return score


def _artifact_priority_score(artifact: DreamArtifact, *, previous_artifact: DreamArtifact | None) -> int:
    pending = [proposal for proposal in artifact.proposals if proposal_state(proposal) == "pending"]
    approved = [proposal for proposal in artifact.proposals if proposal_state(proposal) == "approved"]
    actionable = [proposal for proposal in artifact.proposals if proposal_state(proposal) in {"pending", "approved"}]

    blocker = 0
    if artifact.validation_errors or artifact.status == "invalid":
        blocker = 40
    elif pending and actionable:
        blocker = 25
    elif approved and artifact.status != "applied":
        blocker = 20

    target_kinds = []
    seen_target_kinds: set[str] = set()
    for proposal in artifact.proposals:
        if proposal.target_kind not in seen_target_kinds:
            seen_target_kinds.add(proposal.target_kind)
            target_kinds.append(proposal.target_kind)
    value = 0
    if target_kinds:
        first_kind = target_kinds[0]
        value += TARGET_KIND_WEIGHT.get(first_kind, 0) // 2
        for extra_kind in target_kinds[1:4]:
            value += 2
        value = min(value, 30)

    current_theme_keys = {_proposal_theme_key(proposal) for proposal in artifact.proposals}
    previous_theme_keys = {_proposal_theme_key(proposal) for proposal in previous_artifact.proposals} if previous_artifact else set()
    recurrence = 0
    if previous_theme_keys and current_theme_keys & previous_theme_keys:
        recurrence += 8
    theme_counts = Counter(_proposal_theme_key(proposal) for proposal in artifact.proposals)
    if any(count >= 2 for count in theme_counts.values()):
        recurrence += 7
    recurrence = min(recurrence, 15)

    if previous_artifact is None:
        freshness = 10
    else:
        previous_signature = [
            (
                proposal.id,
                proposal.target_kind,
                proposal.target_path,
                proposal.mode,
                proposal.summary,
                proposal.proposed_text,
                round(proposal.confidence, 3),
                tuple(proposal.provenance),
                proposal_state(proposal),
            )
            for proposal in previous_artifact.proposals
        ]
        current_signature = [
            (
                proposal.id,
                proposal.target_kind,
                proposal.target_path,
                proposal.mode,
                proposal.summary,
                proposal.proposed_text,
                round(proposal.confidence, 3),
                tuple(proposal.provenance),
                proposal_state(proposal),
            )
            for proposal in artifact.proposals
        ]
        if current_signature != previous_signature:
            freshness = 10
        elif artifact.audit_events != previous_artifact.audit_events:
            freshness = 5
        else:
            freshness = 0

    confidences = [proposal.confidence for proposal in artifact.proposals]
    if confidences:
        average_confidence = sum(confidences) / len(confidences)
    else:
        average_confidence = 0.0
    if average_confidence >= 0.90:
        readiness = 10
    elif average_confidence >= 0.80:
        readiness = 7
    elif average_confidence >= 0.70:
        readiness = 3
    else:
        readiness = 0

    noise = 0
    conflicting_paths = _proposal_conflicts(artifact.proposals)
    if any(not proposal.provenance for proposal in artifact.proposals):
        noise += 10
    if conflicting_paths:
        noise += 10
    if any(proposal.rejected and not (proposal.rejection_reason or "").strip() for proposal in artifact.proposals):
        noise += 5
    if any(proposal.summary.strip().lower() in {"misc", "noise", "slop"} for proposal in artifact.proposals):
        noise += 5

    priority = blocker + value + recurrence + freshness + readiness - noise
    return max(0, min(100, int(round(priority))))


def _proposal_sort_key(proposal: DreamProposal, *, score: int) -> tuple[int, int, float, str]:
    kind_rank = {"user": 0, "skill": 1, "memory": 2, "fact": 3}.get(proposal.target_kind, 4)
    evidence_rank = -len(proposal.provenance)
    return (-score, kind_rank, -proposal.confidence, proposal.id)


def _build_proposal_views(artifact: DreamArtifact, artifact_dir: Path, previous_artifact: DreamArtifact | None) -> list[DigestProposalView]:
    previous_theme_keys = {_proposal_theme_key(proposal) for proposal in previous_artifact.proposals} if previous_artifact else set()
    theme_counts = Counter(_proposal_theme_key(proposal) for proposal in artifact.proposals)
    conflicting_paths = _proposal_conflicts(artifact.proposals)
    artifact_text = _safe_quote(artifact_dir)

    views: list[DigestProposalView] = []
    scored_proposals: list[tuple[DreamProposal, int]] = []
    for proposal in artifact.proposals:
        score = _proposal_score(
            proposal,
            previous_theme_keys=previous_theme_keys,
            theme_counts=theme_counts,
            conflicting_paths=conflicting_paths,
        )
        scored_proposals.append((proposal, score))

    for proposal, score in sorted(scored_proposals, key=lambda item: _proposal_sort_key(item[0], score=item[1])):
        views.append(
            DigestProposalView(
                id=proposal.id,
                state=proposal_state(proposal),
                target_kind=proposal.target_kind,
                target_path=proposal.target_path,
                summary=proposal.summary,
                confidence=proposal.confidence,
                risk=proposal.risk,
                priority=proposal.priority,
                reason=proposal.reason,
                source_quote=proposal.source_quote or proposal.snippet,
                policy_flags=list(proposal.policy_flags),
                provenance=list(proposal.provenance),
                score=score,
                approve_command=f"dreaming approve {artifact_text} {proposal.id}",
                reject_command=f'dreaming reject {artifact_text} {proposal.id} --reason "..."',
                theme_key=_proposal_theme_key(proposal),
                rejection_reason=proposal.rejection_reason,
            )
        )
    return views


def _previous_successful_artifact(artifact: DreamArtifact, artifact_root: Path, state_root: Path) -> DreamArtifact | None:
    artifacts = list_artifacts(artifact_root)
    if not artifacts:
        return None

    artifact_by_id = {item.artifact_id: item for item in artifacts}
    runs = state_module.read_run_ledger(ledger_path=state_root / "runs.jsonl")
    current_key = _artifact_source_key(artifact)
    previous_candidates: list[DreamArtifact] = []

    current_run_index = None
    for index, record in enumerate(runs):
        if str(record.get("artifact_id", "")) == artifact.artifact_id:
            current_run_index = index
            break

    ordered_runs = runs[:current_run_index] if current_run_index is not None else runs
    for record in reversed(ordered_runs):
        if not record.get("success"):
            continue
        candidate_id = str(record.get("artifact_id", ""))
        candidate = artifact_by_id.get(candidate_id)
        if candidate is None or candidate.artifact_id == artifact.artifact_id:
            continue
        previous_candidates.append(candidate)
        if _artifact_source_key(candidate) == current_key:
            return candidate

    if previous_candidates:
        return previous_candidates[0]
    return None


def _state_summary(artifact: DreamArtifact) -> dict[str, int]:
    counts = Counter(proposal_state(proposal) for proposal in artifact.proposals)
    return dict(sorted(counts.items()))


def _next_step_text(artifact: DreamArtifact) -> str:
    counts = _state_summary(artifact)
    pending = counts.get("pending", 0)
    approved = counts.get("approved", 0)
    rejected = counts.get("rejected", 0)
    applied = counts.get("applied", 0)
    if pending:
        return "Next step: approve or reject proposals"
    if approved and not applied:
        return "Next step: apply approved proposals"
    if artifact.status in {"applied", "discarded"} or applied:
        return "Next step: run status or compact"
    if rejected and not approved:
        return "Next step: review the rejected proposals"
    return "Next step: run status or compact"


def _proposal_descriptor(proposal: DreamProposal, *, score: int, artifact_dir: Path) -> list[str]:
    artifact_text = _safe_quote(artifact_dir)
    approve_cmd = f"dreaming approve {artifact_text} {proposal.id}"
    reject_cmd = f'dreaming reject {artifact_text} {proposal.id} --reason "..."'
    lines = [
        f"- `{proposal.id}` [{proposal_state(proposal)}] `{proposal.target_kind}` -> `{proposal.target_path}`",
        f"  - summary: {proposal.summary}",
        f"  - confidence: `{proposal.confidence:.2f}`",
        f"  - risk/priority: `{proposal.risk}` / `{proposal.priority}`",
        f"  - score: `{score}`",
        f"  - approve: `{approve_cmd}`",
        f"  - reject: `{reject_cmd}`",
    ]
    if proposal.reason:
        lines.append(f"  - reason: {proposal.reason}")
    if proposal.source_quote:
        lines.append(f"  - source quote: {proposal.source_quote}")
    if proposal.policy_flags:
        lines.append(f"  - policy flags: {', '.join(proposal.policy_flags)}")
    if proposal.rejection_reason:
        lines.append(f"  - rejection reason: {proposal.rejection_reason}")
    if proposal.provenance:
        lines.append(f"  - provenance: {', '.join(proposal.provenance)}")
    else:
        lines.append("  - provenance: none")
    lines.append(f"  - theme: {_proposal_theme_key(proposal)}")
    return lines


def _delta_lines(current: DreamArtifact, previous: DreamArtifact | None) -> list[str]:
    if previous is None:
        return ["- No prior successful dream found."]

    previous_by_id = {proposal.id: proposal for proposal in previous.proposals}
    current_by_id = {proposal.id: proposal for proposal in current.proposals}
    previous_theme_keys = {_proposal_theme_key(proposal) for proposal in previous.proposals}
    current_theme_keys = {_proposal_theme_key(proposal) for proposal in current.proposals}

    new_items = [proposal for proposal in current.proposals if proposal.id not in previous_by_id]
    changed_items = []
    resolved_items = []
    removed_items = [proposal for proposal in previous.proposals if proposal.id not in current_by_id]
    repeated_items = sorted(current_theme_keys & previous_theme_keys)

    for proposal in current.proposals:
        prior = previous_by_id.get(proposal.id)
        if prior is None:
            continue
        if (
            prior.summary != proposal.summary
            or round(prior.confidence, 3) != round(proposal.confidence, 3)
            or prior.target_kind != proposal.target_kind
            or prior.target_path != proposal.target_path
            or prior.proposed_text != proposal.proposed_text
        ):
            changed_items.append(
                f"{proposal.id} confidence {prior.confidence:.2f} -> {proposal.confidence:.2f}"
                if round(prior.confidence, 3) != round(proposal.confidence, 3)
                else f"{proposal.id} updated"
            )
        previous_state = proposal_state(prior)
        current_state = proposal_state(proposal)
        if previous_state != current_state and current_state in {"approved", "rejected", "applied"}:
            resolved_items.append(f"{proposal.id} {previous_state} -> {current_state}")

    lines = [
        f"- New: {len(new_items)} proposal(s)" + (f" ({', '.join(p.id for p in new_items)})" if new_items else ""),
        f"- Changed: {len(changed_items)}" + (f" ({'; '.join(changed_items)})" if changed_items else ""),
        f"- Resolved: {len(resolved_items)}" + (f" ({'; '.join(resolved_items)})" if resolved_items else ""),
        f"- Repeated: {len(repeated_items)} theme(s)" + (f" ({', '.join(repeated_items)})" if repeated_items else ""),
        f"- Removed: {len(removed_items)} proposal(s)" + (f" ({', '.join(p.id for p in removed_items)})" if removed_items else ""),
    ]

    if not any([new_items, changed_items, resolved_items, repeated_items, removed_items]):
        lines.append("- Stalled: nothing material changed since the last dream.")
    return lines


def _artifact_theme_occurrences(artifacts: Iterable[DreamArtifact]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for artifact in artifacts:
        unique_theme_keys = {_proposal_theme_key(proposal) for proposal in artifact.proposals}
        for theme_key in unique_theme_keys:
            counts[theme_key] += 1
    return counts


def _weekly_rollup(artifact: DreamArtifact, artifact_root: Path, state_root: Path, previous_artifact: DreamArtifact | None) -> DigestWeeklyRollup | None:
    artifacts = list_artifacts(artifact_root)
    if not artifacts and not artifact.proposals:
        return None

    runs = state_module.read_run_ledger(ledger_path=state_root / "runs.jsonl")
    anchors: list[datetime] = []
    for record in runs:
        ts = _parse_iso8601(str(record.get("timestamp", "")))
        if ts is not None:
            anchors.append(ts)
    current_ts = _parse_iso8601(artifact.created_at)
    if current_ts is not None:
        anchors.append(current_ts)
    if not anchors:
        return None
    anchor = max(anchors)
    cutoff = anchor - timedelta(days=7)

    accepted: Counter[str] = Counter()
    rejected: Counter[str] = Counter()
    target_kind_accepts: Counter[str] = Counter()
    target_kind_rejects: Counter[str] = Counter()
    theme_occurrences = _artifact_theme_occurrences(a for a in artifacts if (_parse_iso8601(a.created_at) or anchor) >= cutoff)
    candidate_artifacts = [a for a in artifacts if (_parse_iso8601(a.created_at) or anchor) >= cutoff]

    for candidate in candidate_artifacts:
        for event in candidate.audit_events:
            ts = _parse_iso8601(str(event.get("timestamp", "")))
            if ts is not None and ts < cutoff:
                continue
            proposal_id = str(event.get("proposal_id", ""))
            proposal = next((item for item in candidate.proposals if item.id == proposal_id), None)
            if proposal is None:
                continue
            theme_key = _proposal_theme_key(proposal)
            to_state = str(event.get("to_state", "")).lower()
            if to_state in {"approved", "applied"}:
                accepted[theme_key] += 1
                target_kind_accepts[proposal.target_kind] += 1
            elif to_state == "rejected":
                rejected[theme_key] += 1
                target_kind_rejects[proposal.target_kind] += 1

    accepted_themes = sorted(accepted.items(), key=lambda item: (-item[1], item[0]))[:5]
    rejected_themes = sorted(rejected.items(), key=lambda item: (-item[1], item[0]))[:5]
    recurring_themes = sorted(((theme, count) for theme, count in theme_occurrences.items() if count > 1), key=lambda item: (-item[1], item[0]))[:5]

    decision_patterns: list[str] = []
    acceptance_rates: list[tuple[str, float, int, int]] = []
    for target_kind in sorted(set(target_kind_accepts) | set(target_kind_rejects)):
        accepted_count = target_kind_accepts.get(target_kind, 0)
        rejected_count = target_kind_rejects.get(target_kind, 0)
        total = accepted_count + rejected_count
        if total >= 2:
            acceptance_rates.append((target_kind, accepted_count / total, accepted_count, rejected_count))
    acceptance_rates.sort(key=lambda item: (-item[1], item[0]))
    if len(acceptance_rates) >= 2:
        best = acceptance_rates[0]
        worst = acceptance_rates[-1]
        if best[1] - worst[1] >= 0.15:
            decision_patterns.append(
                f"`{best[0]}` proposals are approved more often than `{worst[0]}` proposals ({best[2]}/{best[2] + best[3]} vs {worst[2]}/{worst[2] + worst[3]})"
            )
    if any(theme_occurrences[theme] > 1 and rejected[theme] >= accepted[theme] for theme in theme_occurrences):
        decision_patterns.append("low-confidence duplicates get rejected fast")
    if not decision_patterns:
        decision_patterns.append("not enough data to infer a stable decision pattern yet")

    watchlist_seed = sorted(
        {
            theme: rejected.get(theme, 0) * 2 + theme_occurrences.get(theme, 0) - accepted.get(theme, 0)
            for theme in set(theme_occurrences) | set(rejected)
        }.items(),
        key=lambda item: (-item[1], item[0]),
    )
    watchlist = [theme for theme, score in watchlist_seed if score > 0][:5]
    if not watchlist:
        watchlist = ["none"]

    return DigestWeeklyRollup(
        accepted_themes=accepted_themes,
        rejected_themes=rejected_themes,
        recurring_themes=recurring_themes,
        decision_patterns=decision_patterns,
        watchlist=watchlist,
    )


def build_digest(
    artifact_dir: Path,
    *,
    artifact_root: Path | None = None,
    state_root: Path | None = None,
    include_weekly: bool = False,
) -> DigestResult:
    artifact_dir = Path(artifact_dir)
    artifact = load_artifact(artifact_dir)
    artifact_root = Path(artifact_root) if artifact_root is not None else artifact_dir.parent
    state_root = Path(state_root) if state_root is not None else state_module.STATE_ROOT
    previous = _previous_successful_artifact(artifact, artifact_root, state_root)
    proposal_views = _build_proposal_views(artifact, artifact_dir, previous)
    priority_score = _artifact_priority_score(artifact, previous_artifact=previous)
    delta_lines = _delta_lines(artifact, previous)
    next_step = _next_step_text(artifact)
    weekly_rollup = _weekly_rollup(artifact, artifact_root, state_root, previous) if include_weekly else None
    return DigestResult(
        artifact=artifact,
        artifact_root=artifact_root,
        state_root=state_root,
        previous_artifact_id=previous.artifact_id if previous is not None else None,
        priority_score=priority_score,
        proposal_views=proposal_views,
        delta_lines=delta_lines,
        next_step=next_step,
        weekly_rollup=weekly_rollup,
    )


def render_digest(result: DigestResult) -> str:
    artifact = result.artifact
    artifact_dir = result.artifact_root / artifact.artifact_id
    live_root = Path(artifact.workspace_root)
    counts = _state_summary(artifact)
    target_kind_breakdown = Counter(proposal.target_kind for proposal in artifact.proposals)
    theme_labels = sorted({_proposal_theme_key(proposal) for proposal in artifact.proposals})
    lines = [
        "# Hermes Dreaming digest",
        "",
        f"- Artifact: `{artifact.artifact_id}`",
        f"- Created: `{artifact.created_at}`",
        f"- Provider: `{artifact.provider}`",
        f"- Status: `{artifact.status}`",
        f"- Priority: `{result.priority_score}/100`",
        f"- Previous successful dream: `{result.previous_artifact_id}`" if result.previous_artifact_id else "- Previous successful dream: none",
        f"- Next step: {result.next_step}",
        "",
        "## Status snapshot",
        "",
        f"- Artifact dir: `{artifact_dir}`",
        f"- Live root: `{live_root}`",
        f"- Sources scanned: `{len(artifact.sources)}`",
        f"- Proposals staged: `{len(artifact.proposals)}`",
        f"- Validation state: `{('invalid' if artifact.validation_errors or artifact.status == 'invalid' else 'valid')}`",
        f"- Apply state: `{('applied' if artifact.status == 'applied' or artifact.applied_at else 'not applied')}`",
        f"- Discard state: `{('discarded' if artifact.status == 'discarded' or artifact.discarded_at else 'not discarded')}`",
        f"- Proposal states: pending={counts.get('pending', 0)}, approved={counts.get('approved', 0)}, rejected={counts.get('rejected', 0)}, applied={counts.get('applied', 0)}",
        f"- Target kinds: {', '.join(f'{kind}={count}' for kind, count in sorted(target_kind_breakdown.items())) if target_kind_breakdown else 'none'}",
        f"- Theme labels: {', '.join(f'`{label}`' for label in theme_labels) if theme_labels else 'none'}",
        f"- Applied proposal ids: {', '.join(f'`{proposal_id}`' for proposal_id in artifact.applied_proposal_ids) if artifact.applied_proposal_ids else 'none'}",
        f"- Backup copies: `{len(artifact.backup_paths)}`",
        "",
        "## Priority-ranked proposals",
        "",
    ]

    if result.proposal_views:
        for proposal_view in result.proposal_views:
            proposal = next(item for item in artifact.proposals if item.id == proposal_view.id)
            lines.extend(_proposal_descriptor(proposal, score=proposal_view.score, artifact_dir=artifact_dir))
            lines.append("")
    else:
        lines.extend(["- None", ""])

    lines.extend([
        "## What changed since last dream",
        "",
    ])
    lines.extend(result.delta_lines)
    lines.append("")

    artifact_text = _safe_quote(artifact_dir)
    live_root_text = _safe_quote(live_root)
    artifact_root_text = _safe_quote(result.artifact_root)
    summarize_cmd = f"dreaming summarize {artifact_text}"
    approve_all_cmd = f"dreaming approve {artifact_text} all"
    reject_one_cmd = f'dreaming reject {artifact_text} <proposal-id> --reason "..."'
    diff_cmd = f"dreaming diff {artifact_text} --live-root {live_root_text}"
    validate_cmd = f"dreaming validate {artifact_text} --live-root {live_root_text}"
    apply_cmd = f"dreaming apply {artifact_text} --live-root {live_root_text} --backup-root <backup-root>"
    status_cmd = f"dreaming status --artifact-root {artifact_root_text}"

    lines.extend([
        "## Action loop",
        "",
        f"- {result.next_step}",
        f"- summarize: `{summarize_cmd}`",
        f"- approve all: `{approve_all_cmd}`",
        f"- reject one: `{reject_one_cmd}`",
        f"- diff: `{diff_cmd}`",
        f"- validate: `{validate_cmd}`",
        f"- apply: `{apply_cmd}`",
        f"- status: `{status_cmd}`",
        "",
    ])

    if result.weekly_rollup is not None:
        lines.extend([
            "## Weekly rollup",
            "",
            "- Accepted themes:",
        ])
        if result.weekly_rollup.accepted_themes:
            for theme, count in result.weekly_rollup.accepted_themes:
                lines.append(f"  - {theme}, {count} win(s)")
        else:
            lines.append("  - none")
        lines.append("- Rejected themes:")
        if result.weekly_rollup.rejected_themes:
            for theme, count in result.weekly_rollup.rejected_themes:
                lines.append(f"  - {theme}, {count} rejection(s)")
        else:
            lines.append("  - none")
        lines.append("- Recurring themes:")
        if result.weekly_rollup.recurring_themes:
            for theme, count in result.weekly_rollup.recurring_themes:
                lines.append(f"  - {theme}, {count} appearance(s)")
        else:
            lines.append("  - none")
        lines.append("- Decision patterns:")
        for pattern in result.weekly_rollup.decision_patterns:
            lines.append(f"  - {pattern}")
        lines.append("- Next-week watchlist:")
        for item in result.weekly_rollup.watchlist:
            lines.append(f"  - {item}")
        lines.append("")

    lines.append("Delivery: local only, no Telegram send by default.")
    lines.append("Wire delivery later by wrapping this command in a separate transport layer that consumes stdout.")
    return "\n".join(lines).rstrip() + "\n"


@dataclass(slots=True)
class InboxDigestResult:
    artifact_root: str
    total_artifacts: int
    active_artifacts: int
    high_risk_count: int
    high_priority_count: int
    apply_ready_count: int
    apply_ready_rows: list[Any]
    newest_artifact_id: str | None
    top_reason: str
    needs_tony_rows: list[Any]
    safe_to_ignore_rows: list[Any]


def _inbox_attention_key(row: object) -> tuple[int, int, str]:
    priority = str(getattr(row, "highest_priority", "normal") or "normal").lower()
    risk = str(getattr(row, "highest_risk", "low") or "low").lower()
    created_at = str(getattr(row, "created_at", ""))
    return (
        -PRIORITY_ORDER.get(priority, 0),
        -RISK_ORDER.get(risk, 0),
        created_at,
    )


def build_inbox_digest(
    artifact_root: Path,
    *,
    state_filter: set[str] | None = None,
    priority_filter: set[str] | None = None,
    state_root: Path | None = None,
    limit: int | None = None,
) -> InboxDigestResult:
    inbox = build_inbox(
        artifact_root,
        state_filter=state_filter,
        priority_filter=priority_filter,
        apply_ready=True,
        limit=limit,
    )
    rows = list(inbox.rows)
    # We re-fetch without apply_ready to also report the full needs-tony / safe-to-ignore sets.
    full_inbox = build_inbox(
        artifact_root,
        state_filter=state_filter,
        priority_filter=priority_filter,
        limit=limit,
    )
    full_rows = list(full_inbox.rows)
    active_rows = [row for row in full_rows if row.inbox_state in {"staged", "mixed", "approved", "invalid", "pending"}]
    high_risk_count = sum(1 for row in full_rows if row.highest_risk == "high")
    high_priority_count = sum(1 for row in full_rows if row.highest_priority == "high")
    newest_artifact_id = max(full_rows, key=lambda row: row.created_at).artifact_id if full_rows else None
    top_reason = next((row.top_reason for row in full_rows if row.top_reason != "none"), "none")
    needs_tony_rows = sorted(
        [
            row
            for row in full_rows
            if row.highest_priority == "high" or row.highest_risk == "high" or row.inbox_state in {"mixed", "invalid", "staged"}
        ],
        key=_inbox_attention_key,
    )
    if not needs_tony_rows and full_rows:
        needs_tony_rows = full_rows[: min(3, len(full_rows))]
    safe_to_ignore_rows = sorted([row for row in full_rows if row not in needs_tony_rows], key=_inbox_attention_key)
    return InboxDigestResult(
        artifact_root=str(artifact_root),
        total_artifacts=full_inbox.total_artifacts,
        active_artifacts=len(active_rows),
        high_risk_count=high_risk_count,
        high_priority_count=high_priority_count,
        apply_ready_count=len(rows),
        apply_ready_rows=rows,
        newest_artifact_id=newest_artifact_id,
        top_reason=top_reason,
        needs_tony_rows=needs_tony_rows,
        safe_to_ignore_rows=safe_to_ignore_rows,
    )


def _render_inbox_digest_rows(rows: list[Any]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        flags = ", ".join(getattr(row, "policy_flags", []) or []) or "none"
        lines.append(
            f"- `{getattr(row, 'artifact_id', 'unknown')}` [{getattr(row, 'inbox_state', 'unknown')}] "
            f"risk `{getattr(row, 'highest_risk', 'low')}` / priority `{getattr(row, 'highest_priority', 'normal')}`"
        )
        lines.append(f"  - age: {getattr(row, 'age', 'unknown age')}")
        lines.append(f"  - reason: {getattr(row, 'top_reason', 'none')}")
        lines.append(f"  - policy flags: {flags}")
        lines.append(f"  - next: `{getattr(row, 'next_command', 'dreaming summarize <artifact>')}`")
    if not lines:
        lines.append("- none")
    return lines


def render_inbox_digest(result: InboxDigestResult) -> str:
    lines = [
        "# Hermes Dreaming inbox digest",
        "",
        f"- Artifact root: `{result.artifact_root}`",
        f"- Total artifacts: `{result.total_artifacts}`",
        f"- Active artifacts: `{result.active_artifacts}`",
        f"- High risk count: `{result.high_risk_count}`",
        f"- High priority count: `{result.high_priority_count}`",
        f"- Apply-ready count: `{result.apply_ready_count}`",
        f"- Newest artifact: `{result.newest_artifact_id}`" if result.newest_artifact_id else "- Newest artifact: none",
        f"- Top reason: {result.top_reason}",
        "",
        "## Ready to apply",
        "",
    ]
    lines.extend(_render_inbox_digest_rows(result.apply_ready_rows))
    lines.extend(["", "## Needs Tony", ""])
    lines.extend(_render_inbox_digest_rows(result.needs_tony_rows))
    lines.extend(["", "## Safe to ignore", ""])
    lines.extend(_render_inbox_digest_rows(result.safe_to_ignore_rows))
    lines.append("")
    lines.append("Delivery: local only, no Telegram send by default.")
    lines.append("Wire delivery later by wrapping this command in a separate transport layer that consumes stdout.")
    return "\n".join(lines).rstrip() + "\n"
