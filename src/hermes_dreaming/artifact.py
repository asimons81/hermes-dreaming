
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any


ARTIFACT_MANIFEST = 'manifest.json'
REPORT_FILE = 'REPORT.md'
SOURCES_FILE = 'sources.jsonl'
PROPOSALS_FILE = 'proposals.jsonl'
VALID_TARGET_KINDS = {'memory', 'user', 'skill', 'fact'}
VALID_MODES = {'append_text', 'jsonl_append'}


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


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
    apply_started_at: str | None = None
    apply_finished_at: str | None = None
    applied_at: str | None = None
    discarded_at: str | None = None

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
            apply_started_at=data.get('apply_started_at'),
            apply_finished_at=data.get('apply_finished_at'),
            applied_at=data.get('applied_at'),
            discarded_at=data.get('discarded_at'),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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

    return artifact_dir


def load_artifact(artifact_dir: Path) -> DreamArtifact:
    artifact_dir = Path(artifact_dir)
    data = json.loads((artifact_dir / ARTIFACT_MANIFEST).read_text(encoding='utf-8'))
    return DreamArtifact.from_dict(data)


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
