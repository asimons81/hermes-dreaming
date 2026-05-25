from __future__ import annotations

from dataclasses import dataclass
import json
import re
from pathlib import Path
from typing import Protocol

from .artifact import DreamProposal, SourceSnapshot

MARKER_RE = re.compile(r"^\s*(?:-\s*)?DREAM:\s*(memory|user|skill|fact)\s*:\s*(.+?)\s*$", re.IGNORECASE)


@dataclass(slots=True)
class DreamContext:
    workspace_root: Path
    live_root: Path
    artifact_dir: Path
    source_roots: list[Path]
    model: str | None = None


class DreamProvider(Protocol):
    name: str

    def generate(self, sources: list[SourceSnapshot], context: DreamContext) -> tuple[str, list[DreamProposal], list[str]]:
        raise NotImplementedError


@dataclass(slots=True)
class OfflineMarkerProvider:
    name: str = "offline-marker"

    def generate(self, sources: list[SourceSnapshot], context: DreamContext) -> tuple[str, list[DreamProposal], list[str]]:
        proposals: list[DreamProposal] = []
        notes: list[str] = []

        for source in sources:
            for line_number, line in enumerate(source.content.splitlines(), start=1):
                match = MARKER_RE.match(line)
                if not match:
                    continue
                kind, payload = match.groups()
                proposal = self._build_proposal(kind.lower(), payload.strip(), source, line_number)
                if proposal is not None:
                    proposals.append(proposal)

        proposals.sort(key=lambda item: (item.target_kind, item.target_path, item.id))
        if not proposals:
            notes.append("No DREAM markers were found in the supplied sources.")
        report = self._build_report(sources, proposals, context, notes)
        return report, proposals, notes

    def _build_proposal(self, kind: str, payload: str, source: SourceSnapshot, line_number: int) -> DreamProposal | None:
        provenance = [f"{source.path}:{line_number}"]
        if kind in {"memory", "user"}:
            text = payload if payload.startswith("-") else f"- {payload}"
            return DreamProposal(
                id=f"{kind}-{source.sha256[:8]}-{line_number}",
                target_kind=kind,
                target_path=f"{kind}.md",
                mode="append_text",
                summary=f"append {kind} note from {Path(source.path).name}",
                provenance=provenance,
                proposed_text=text,
                approved=False,
            )

        if kind == "fact":
            parsed = self._parse_fact_payload(payload)
            if parsed is None:
                return None
            return DreamProposal(
                id=f"fact-{source.sha256[:8]}-{line_number}",
                target_kind="fact",
                target_path="facts.jsonl",
                mode="jsonl_append",
                summary=f"append fact from {Path(source.path).name}",
                provenance=provenance,
                proposed_text=json.dumps(parsed, sort_keys=True, ensure_ascii=False),
                approved=False,
            )

        if kind == "skill":
            target_path, body = self._parse_skill_payload(payload)
            if not target_path:
                return None
            body = body.strip()
            text = body if body.startswith("#") else f"## Dreaming note\n\n- {body}\n\nSource: {source.path}:{line_number}\n"
            return DreamProposal(
                id=f"skill-{source.sha256[:8]}-{line_number}",
                target_kind="skill",
                target_path=target_path,
                mode="append_text",
                summary=f"stage skill note for {target_path}",
                provenance=provenance,
                proposed_text=text,
                approved=False,
            )

        return None

    def _parse_skill_payload(self, payload: str) -> tuple[str | None, str]:
        if "|" not in payload:
            return None, payload
        left, right = payload.split("|", 1)
        target_path: str | None = None
        for chunk in left.split(";"):
            key, _, value = chunk.partition("=")
            if key.strip().lower() == "path":
                target_path = value.strip()
        return target_path, right.strip()

    def _parse_fact_payload(self, payload: str) -> dict[str, object] | None:
        payload = payload.strip()
        if payload.startswith("{") and payload.endswith("}"):
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:
                return None
            return parsed if isinstance(parsed, dict) else {"fact": parsed}
        return {"fact": payload}

    def _build_report(
        self,
        sources: list[SourceSnapshot],
        proposals: list[DreamProposal],
        context: DreamContext,
        notes: list[str],
    ) -> str:
        lines = [
            "# Hermes Dreaming Report",
            "",
            f"- Provider: `{self.name}`",
            f"- Workspace: `{context.workspace_root}`",
            f"- Live root: `{context.live_root}`",
            f"- Sources scanned: `{len(sources)}`",
            f"- Proposals staged: `{len(proposals)}`",
            "",
        ]
        if notes:
            lines.extend(["## Notes", ""])
            for note in notes:
                lines.append(f"- {note}")
            lines.append("")
        lines.extend(["## Proposals", ""])
        if proposals:
            for proposal in proposals:
                lines.append(f"- `{proposal.id}` -> `{proposal.target_path}` ({proposal.mode})")
                lines.append(f"  - {proposal.summary}")
                lines.append(f"  - Provenance: {', '.join(proposal.provenance)}")
        else:
            lines.append("- None")
        lines.append("")
        return "\n".join(lines)


@dataclass(slots=True)
class OpenAICompatibleProvider:
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    base_url: str | None = None
    name: str = "openai-compatible"

    def generate(self, sources: list[SourceSnapshot], context: DreamContext) -> tuple[str, list[DreamProposal], list[str]]:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("openai is not installed; install the 'llm' extra to use this provider") from exc

        client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        prompt = self._build_prompt(sources, context)
        response = client.responses.create(model=self.model, input=prompt, temperature=0)
        text = getattr(response, "output_text", "").strip()
        if not text:
            raise RuntimeError("provider returned no text")
        payload = json.loads(text)
        report = str(payload.get("report", "# Hermes Dreaming Report\n\nNo report provided.\n"))
        proposals = [DreamProposal.from_dict(item) for item in payload.get("proposals", [])]
        notes = [str(item) for item in payload.get("notes", [])]
        return report, proposals, notes

    def _build_prompt(self, sources: list[SourceSnapshot], context: DreamContext) -> str:
        source_block = "\n\n".join(f"### {source.path}\n{source.content}" for source in sources)
        return (
            "You are Hermes Dreaming, a staged self-improvement engine.\n"
            "Return JSON only with keys: report, proposals, notes.\n"
            "Each proposal must include id, target_kind, target_path, mode, summary, provenance, proposed_text, approved.\n"
            "Never include secrets, tokens, or hardcoded personal data.\n\n"
            f"Workspace root: {context.workspace_root}\n"
            f"Live root: {context.live_root}\n"
            f"Sources:\n{source_block}\n"
        )


def build_provider(name: str, *, model: str | None = None, api_key: str | None = None, base_url: str | None = None) -> DreamProvider:
    normalized = name.lower().strip()
    if normalized in {"offline", "offline-marker", "marker"}:
        return OfflineMarkerProvider()
    if normalized in {"openai", "openai-compatible"}:
        return OpenAICompatibleProvider(model=model or "gpt-4o-mini", api_key=api_key, base_url=base_url)
    raise ValueError(f"unknown provider: {name}")
