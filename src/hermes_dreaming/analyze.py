from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .artifact import DreamArtifact, write_artifact
from .collect import collect_sources
from .providers import DreamContext, build_provider
from .validation import validate_artifact


@dataclass(slots=True)
class DreamCreationResult:
    artifact: DreamArtifact
    artifact_dir: Path
    validation_errors: list[str]


@dataclass(slots=True)
class DreamRunConfig:
    live_root: Path
    artifact_root: Path
    source_paths: list[Path]
    provider_name: str = "offline-marker"
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def generate_artifact_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"


def build_report(artifact: DreamArtifact) -> str:
    lines = [
        "# Hermes Dreaming Report",
        "",
        f"- Artifact: `{artifact.artifact_id}`",
        f"- Created: `{artifact.created_at}`",
        f"- Provider: `{artifact.provider}`",
        f"- Status: `{artifact.status}`",
        f"- Sources scanned: `{len(artifact.sources)}`",
        f"- Proposals staged: `{len(artifact.proposals)}`",
        "",
    ]
    if artifact.validation_errors:
        lines.extend(["## Validation", ""])
        for error in artifact.validation_errors:
            lines.append(f"- {error}")
        lines.append("")
    lines.extend(["## Proposals", ""])
    if artifact.proposals:
        for proposal in artifact.proposals:
            lines.append(f"- `{proposal.id}` -> `{proposal.target_path}` ({proposal.mode})")
            lines.append(f"  - {proposal.summary}")
            lines.append(f"  - Provenance: {', '.join(proposal.provenance)}")
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def create_dream_artifact(config: DreamRunConfig) -> DreamCreationResult:
    live_root = Path(config.live_root)
    artifact_root = Path(config.artifact_root)
    source_paths = [Path(path) for path in config.source_paths]

    source_snapshots = collect_sources(source_paths)
    artifact_id = generate_artifact_id()
    artifact_dir = artifact_root / artifact_id

    provider = build_provider(config.provider_name, model=config.model, api_key=config.api_key, base_url=config.base_url)
    context = DreamContext(
        workspace_root=live_root,
        live_root=live_root,
        artifact_dir=artifact_dir,
        source_roots=source_paths,
        model=config.model,
    )
    report_body, proposals, _notes = provider.generate(source_snapshots, context)

    artifact = DreamArtifact(
        artifact_id=artifact_id,
        created_at=_now_iso(),
        provider=provider.name,
        status="staged",
        workspace_root=str(live_root),
        source_roots=[str(path) for path in source_paths],
        report=report_body,
        sources=source_snapshots,
        proposals=proposals,
    )

    validation_errors = validate_artifact(artifact, live_root=live_root)
    artifact.validation_errors = validation_errors
    if validation_errors:
        artifact.status = "invalid"
    if not artifact.report.strip():
        artifact.report = build_report(artifact)
    else:
        artifact.report = artifact.report.rstrip() + "\n"

    write_artifact(artifact, artifact_dir)
    return DreamCreationResult(artifact=artifact, artifact_dir=artifact_dir, validation_errors=validation_errors)


def list_artifacts(artifact_root: Path) -> list[DreamArtifact]:
    artifact_root = Path(artifact_root)
    if not artifact_root.exists():
        return []
    artifacts: list[DreamArtifact] = []
    for manifest in sorted(artifact_root.glob("*/manifest.json")):
        try:
            from .artifact import load_artifact

            artifacts.append(load_artifact(manifest.parent))
        except Exception:
            continue
    return artifacts
