from __future__ import annotations

from dataclasses import dataclass
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from .artifact import DreamProposal, SourceSnapshot
from .validation import validate_proposals

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
        payload = self._parse_payload(text)
        report = str(payload.get("report", "# Hermes Dreaming Report\n\nNo report provided.\n"))
        proposals = self._normalize_proposals(payload.get("proposals", []), sources)
        notes = self._normalize_notes(payload.get("notes", []))
        return report, proposals, notes

    def _parse_payload(self, text: str) -> dict[str, object]:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = self._parse_fenced_payload(text)
        if not isinstance(parsed, dict):
            raise RuntimeError("provider returned JSON that is not an object")
        return parsed

    def _parse_fenced_payload(self, text: str) -> object:
        match = re.fullmatch(r"\s*```(?:json)?\s*(.*?)\s*```\s*", text, flags=re.IGNORECASE | re.DOTALL)
        if match is None:
            raise RuntimeError("provider returned malformed JSON")
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise RuntimeError("provider returned malformed fenced JSON") from exc

    def _normalize_notes(self, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        return [str(value)]

    def _normalize_proposals(self, value: object, sources: list[SourceSnapshot]) -> list[DreamProposal]:
        if not isinstance(value, list):
            return []
        proposals: list[DreamProposal] = []
        default_provenance = [source.path for source in sources]
        for item in value:
            proposal = self._normalize_proposal(item, default_provenance)
            if proposal is None:
                continue
            if validate_proposals([proposal]):
                continue
            proposals.append(proposal)
        return proposals

    def _normalize_proposal(self, value: object, default_provenance: list[str]) -> DreamProposal | None:
        if not isinstance(value, dict):
            return None
        required = ["id", "target_kind", "target_path", "mode", "summary", "proposed_text"]
        if any(key not in value for key in required):
            return None
        proposed_text = str(value.get("proposed_text", "")).strip()
        if not proposed_text:
            return None
        provenance_value = value.get("provenance")
        if isinstance(provenance_value, str):
            provenance = [provenance_value]
        elif isinstance(provenance_value, list):
            provenance = [str(item) for item in provenance_value if item is not None and str(item).strip()]
        else:
            provenance = default_provenance
        if not provenance:
            return None
        return DreamProposal.from_dict(
            {
                "id": str(value["id"]),
                "target_kind": str(value["target_kind"]),
                "target_path": str(value["target_path"]),
                "mode": str(value["mode"]),
                "summary": str(value["summary"]),
                "provenance": provenance,
                "proposed_text": proposed_text,
                "approved": False,
                "notes": value.get("notes"),
            }
        )

    def _build_prompt(self, sources: list[SourceSnapshot], context: DreamContext) -> str:
        source_block = "\n\n".join(f"### {source.path}\n{source.content}" for source in sources)
        return (
            "You are Hermes Dreaming, a staged self-improvement engine.\n"
            "Return JSON only with keys: report, proposals, notes.\n"
            "Each proposal must include id, target_kind, target_path, mode, summary, provenance, proposed_text, approved.\n"
            "Allowed target_kind values: memory, user, skill, fact. Never use source filenames as target_kind.\n"
            "Allowed mode values: append_text, jsonl_append. Never use edit/update/replace.\n"
            "Allowed target_path values: memory.md for memory, user.md for user, facts.jsonl for fact, or skills/<name>.md for skill. Never target source files or absolute paths.\n"
            "For user preferences, use target_kind user, target_path user.md, mode append_text, and proposed_text as one concise markdown bullet.\n"
            "For memory notes, use target_kind memory, target_path memory.md, mode append_text, and proposed_text as one concise markdown bullet.\n"
            "For facts, use target_kind fact, target_path facts.jsonl, mode jsonl_append, and proposed_text as a JSON object string.\n"
            "Set approved to false for every proposal.\n"
            "Never include secrets, tokens, or hardcoded personal data.\n\n"
            f"Workspace root: {context.workspace_root}\n"
            f"Live root: {context.live_root}\n"
            f"Sources:\n{source_block}\n"
        )


@dataclass(slots=True)
class OllamaProvider(OpenAICompatibleProvider):
    model: str = "qwen2.5:3b"
    api_key: str | None = None
    base_url: str | None = "http://127.0.0.1:11434"
    name: str = "ollama"
    timeout_seconds: int = 180

    def generate(self, sources: list[SourceSnapshot], context: DreamContext) -> tuple[str, list[DreamProposal], list[str]]:
        prompt = self._build_prompt(sources, context)
        url = f"{(self.base_url or 'http://127.0.0.1:11434').rstrip('/')}/api/chat"
        body = json.dumps(
            {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
            }
        ).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.URLError as exc:  # pragma: no cover - network-specific
            raise RuntimeError(f"ollama request failed: {exc}") from exc
        try:
            response_payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("ollama returned malformed response JSON") from exc
        message = response_payload.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("ollama returned no message")
        text = str(message.get("content", "")).strip()
        if not text:
            raise RuntimeError("ollama returned no text")
        payload = self._parse_payload(text)
        report = str(payload.get("report", "# Hermes Dreaming Report\n\nNo report provided.\n"))
        proposals = self._normalize_proposals(payload.get("proposals", []), sources)
        notes = self._normalize_notes(payload.get("notes", []))
        return report, proposals, notes


def build_provider(name: str, *, model: str | None = None, api_key: str | None = None, base_url: str | None = None) -> DreamProvider:
    normalized = name.lower().strip()
    if normalized in {"offline", "offline-marker", "marker"}:
        return OfflineMarkerProvider()
    if normalized in {"openai", "openai-compatible"}:
        return OpenAICompatibleProvider(model=model or "gpt-4o-mini", api_key=api_key, base_url=base_url)
    if normalized in {"ollama", "ollama-native"}:
        return OllamaProvider(model=model or "qwen2.5:3b", api_key=api_key, base_url=base_url or "http://127.0.0.1:11434")
    raise ValueError(f"unknown provider: {name}")
