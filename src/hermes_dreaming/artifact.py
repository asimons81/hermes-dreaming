from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ARTIFACT_MANIFEST = 'manifest.json'
REPORT_FILE = 'REPORT.md'
SOURCES_FILE = 'sources.jsonl'
PROPOSALS_FILE = 'proposals.jsonl'
AUDIT_FILE = 'audit.jsonl'
VALID_TARGET_KINDS = {'memory', 'user', 'skill', 'fact'}
VALID_MODES = {'append_text', 'jsonl_append'}
VALID_RISK_LEVELS = {'low', 'medium', 'high'}
VALID_PRIORITY_LEVELS = {'low', 'normal', 'high'}


class DreamArtifactStateError(RuntimeError):
    pass


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


@dataclass(eq=True)
class SourceSnapshot:
    path: str
    kind: str
    content: str
    sha256: str
    line_count: int

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'SourceSnapshot':
        return cls(
            path=data['path'],
            kind=data['kind'],
            content=data['content'],
            sha256=data['sha256'],
            line_count=int(data['line_count']),
        )


@dataclass(eq=True)
class DreamProposal:
    id: str
    target_kind: str
    target_path: str
    mode: str
    summary: str
    provenance: list[str]
    proposed_text: str
    approved: bool
    idempotence_key: str | None = None
    policy_version: str | None = None
    confidence: float = 0.0
    snippet: str = ""
    risk: str = "low"
    priority: str = "normal"
    reason: str = ""
    source_quote: str = ""
    policy_flags: list[str] = field(default_factory=list)
    rejected: bool = False
    rejection_reason: str | None = None
    applied: bool = False
    notes: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'DreamProposal':
        return cls(
            id=data['id'],
            target_kind=data['target_kind'],
            target_path=data['target_path'],
            mode=data['mode'],
            summary=data['summary'],
            provenance=list(data.get('provenance', [])),
            proposed_text=data.get('proposed_text', ''),
            approved=bool(data.get('approved', False)),
            idempotence_key=data.get('idempotence_key'),
            policy_version=data.get('policy_version'),
            confidence=float(data.get('confidence', 0.0) or 0.0),
            snippet=str(data.get('snippet', '') or ''),
            risk=str(data.get('risk', 'low') or 'low'),
            priority=str(data.get('priority', 'normal') or 'normal'),
            reason=str(data.get('reason', '') or ''),
            source_quote=str(data.get('source_quote', data.get('snippet', '')) or ''),
            policy_flags=[str(item) for item in data.get('policy_flags', []) or []],
            rejected=bool(data.get('rejected', False)),
            rejection_reason=data.get('rejection_reason'),
            applied=bool(data.get('applied', False)),
            notes=data.get('notes'),
        )


@dataclass(eq=True)
class DreamArtifact:
    artifact_id: str
    created_at: str
    provider: str
    status: str
    workspace_root: str
    source_roots: list[str]
    report: str
    sources: list[SourceSnapshot] = field(default_factory=list)
    proposals: list[DreamProposal] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    apply_errors: list[str] = field(default_factory=list)
    applied_proposal_ids: list[str] = field(default_factory=list)
    backup_paths: list[str] = field(default_factory=list)
    audit_events: list[dict[str, Any]] = field(default_factory=list)
    apply_started_at: str | None = None
    apply_finished_at: str | None = None
    applied_at: str | None = None
    discarded_at: str | None = None
    reverted_at: str | None = None
    revert_audit_events: list[dict[str, Any]] = field(default_factory=list)
    # Ephemeral: only set in-memory during a single apply dry-run call.
    # Not part of the on-disk artifact contract; excluded from to_dict.
    dry_run_report: Any = field(default=None, repr=False, compare=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> 'DreamArtifact':
        return cls(
            artifact_id=data['artifact_id'],
            created_at=data['created_at'],
            provider=data['provider'],
            status=data['status'],
            workspace_root=data['workspace_root'],
            source_roots=list(data.get('source_roots', [])),
            report=data.get('report', ''),
            sources=[SourceSnapshot.from_dict(item) for item in data.get('sources', [])],
            proposals=[DreamProposal.from_dict(item) for item in data.get('proposals', [])],
            validation_errors=list(data.get('validation_errors', []) or []),
            apply_errors=list(data.get('apply_errors', []) or []),
            applied_proposal_ids=list(data.get('applied_proposal_ids', []) or []),
            backup_paths=list(data.get('backup_paths', []) or []),
            audit_events=[dict(item) for item in data.get('audit_events', []) or []],
            apply_started_at=data.get('apply_started_at'),
            apply_finished_at=data.get('apply_finished_at'),
            applied_at=data.get('applied_at'),
            discarded_at=data.get('discarded_at'),
            reverted_at=data.get('reverted_at'),
            revert_audit_events=[dict(item) for item in data.get('revert_audit_events', []) or []],
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("dry_run_report", None)
        return data


def proposal_state(proposal: DreamProposal) -> str:
    if proposal.applied:
        return 'applied'
    if proposal.rejected:
        return 'rejected'
    if proposal.approved:
        return 'approved'
    return 'pending'


def append_audit_event(
    artifact: DreamArtifact,
    proposal: DreamProposal,
    *,
    action: str,
    from_state: str,
    to_state: str,
    reason: str | None = None,
    command: str | None = None,
) -> dict[str, Any]:
    event: dict[str, Any] = {
        'timestamp': _now_iso(),
        'artifact_id': artifact.artifact_id,
        'action': action,
        'proposal_id': proposal.id,
        'target_kind': proposal.target_kind,
        'target_path': proposal.target_path,
        'from_state': from_state,
        'to_state': to_state,
    }
    if reason is not None:
        event['reason'] = reason
    if command is not None:
        event['command'] = command
    artifact.audit_events.append(event)
    return event


def record_proposal_transition(
    artifact: DreamArtifact,
    proposal: DreamProposal,
    *,
    to_state: str,
    reason: str | None = None,
    command: str | None = None,
) -> bool:
    from_state = proposal_state(proposal)
    if proposal.applied and to_state == 'approved':
        return False
    if proposal.applied and to_state != 'applied':
        raise DreamArtifactStateError(f'proposal {proposal.id} is already applied')
    if from_state == to_state:
        if to_state != 'rejected' or (reason is None or proposal.rejection_reason == reason):
            return False

    if to_state == 'approved':
        proposal.approved = True
        proposal.rejected = False
        proposal.rejection_reason = None
    elif to_state == 'rejected':
        proposal.approved = False
        proposal.rejected = True
        proposal.rejection_reason = reason
    elif to_state == 'applied':
        proposal.approved = True
        proposal.rejected = False
        proposal.rejection_reason = None
        proposal.applied = True
    elif to_state == 'pending':
        proposal.approved = False
        proposal.rejected = False
        proposal.rejection_reason = None
        proposal.applied = False
    else:
        raise DreamArtifactStateError(f'unsupported proposal state transition: {to_state!r}')

    append_audit_event(
        artifact,
        proposal,
        action=to_state,
        from_state=from_state,
        to_state=to_state,
        reason=reason,
        command=command,
    )
    return True


def _read_jsonl_records(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return records
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


def write_artifact(artifact: DreamArtifact, artifact_dir: Path) -> Path:
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / ARTIFACT_MANIFEST).write_text(
        json.dumps(artifact.to_dict(), indent=2, ensure_ascii=False) + '\n',
        encoding='utf-8',
    )
    (artifact_dir / REPORT_FILE).write_text(artifact.report, encoding='utf-8')

    with (artifact_dir / SOURCES_FILE).open('w', encoding='utf-8') as handle:
        for source in artifact.sources:
            handle.write(json.dumps(asdict(source), ensure_ascii=False) + '\n')

    with (artifact_dir / PROPOSALS_FILE).open('w', encoding='utf-8') as handle:
        for proposal in artifact.proposals:
            handle.write(json.dumps(asdict(proposal), ensure_ascii=False) + '\n')

    with (artifact_dir / AUDIT_FILE).open('w', encoding='utf-8') as handle:
        for event in artifact.audit_events:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + '\n')

    return artifact_dir


def load_artifact(artifact_dir: Path) -> DreamArtifact:
    artifact_dir = Path(artifact_dir)
    data = json.loads((artifact_dir / ARTIFACT_MANIFEST).read_text(encoding='utf-8'))
    artifact = DreamArtifact.from_dict(data)
    audit_path = artifact_dir / AUDIT_FILE
    if audit_path.exists():
        audit_events = _read_jsonl_records(audit_path)
        if audit_events:
            artifact.audit_events = audit_events
    return artifact


def update_artifact_status(
    artifact_dir: Path,
    status: str,
    *,
    applied_at: str | None = None,
    discarded_at: str | None = None,
) -> DreamArtifact:
    artifact = load_artifact(artifact_dir)
    artifact.status = status
    if applied_at is not None:
        artifact.applied_at = applied_at
    if discarded_at is not None:
        artifact.discarded_at = discarded_at
    write_artifact(artifact, artifact_dir)
    return artifact
