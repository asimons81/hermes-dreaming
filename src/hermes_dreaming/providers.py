from __future__ import annotations

from dataclasses import dataclass
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from .artifact import DreamProposal, SourceSnapshot, text_sha256
from .validation import validate_proposals

MARKER_RE = re.compile(r"^\s*(?:-\s*)?DREAM:\s*(memory|user|skill|fact)\s*:\s*(.+?)\s*$", re.IGNORECASE)


class ProviderOutputError(RuntimeError):
    def __init__(self, provider: str, message: str, *, payload_hash: str | None = None) -> None:
        self.provider = provider
        self.payload_hash = payload_hash
        detail = f"{provider} provider output invalid: {message}"
        if payload_hash:
            detail = f"{detail} [payload_sha256={payload_hash}]"
        super().__init__(detail)


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
        proposals = self._dedupe_proposals(proposals, payload_hash=text_sha256("\n".join(source.sha256 for source in sources)))
        validation_errors = validate_proposals(proposals)
        if validation_errors:
            raise ProviderOutputError(self.name, "; ".join(validation_errors), payload_hash=text_sha256("\n".join(source.sha256 for source in sources)))
        if not proposals:
            notes.append("No DREAM markers were found in the supplied sources.")
        report = self._build_report(sources, proposals, context, notes)
        return report, proposals, notes

    def _build_proposal(self, kind: str, payload: str, source: SourceSnapshot, line_number: int) -> DreamProposal | None:
        provenance = [f"{source.path}:{line_number}"]
        source_quote = source.content.splitlines()[line_number - 1].strip() if line_number <= source.line_count else f"{source.path}:{line_number}"
        snippet = source_quote
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
                confidence=1.0,
                snippet=snippet,
                risk="medium" if kind == "user" else "low",
                priority="normal",
                reason=f"explicit DREAM marker requested a {kind} update",
                source_quote=source_quote,
                policy_flags=["safe_append", "profile_preference" if kind == "user" else "memory_update"],
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
                confidence=1.0,
                snippet=snippet,
                risk="low",
                priority="normal",
                reason="explicit DREAM marker requested a fact update",
                source_quote=source_quote,
                policy_flags=["fact_update", "safe_append"],
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
                confidence=1.0,
                snippet=snippet,
                risk="medium",
                priority="normal",
                reason="explicit DREAM marker requested a skill note",
                source_quote=source_quote,
                policy_flags=["skill_update", "safe_append"],
            )

        return None


    def _dedupe_proposals(self, proposals: list[DreamProposal], *, payload_hash: str) -> list[DreamProposal]:
        deduped: list[DreamProposal] = []
        by_target: dict[str, DreamProposal] = {}
        for proposal in proposals:
            existing = by_target.get(proposal.target_path)
            if existing is None:
                by_target[proposal.target_path] = proposal
                deduped.append(proposal)
                continue

            same_content = (
                existing.target_kind == proposal.target_kind
                and existing.mode == proposal.mode
                and existing.proposed_text == proposal.proposed_text
            )
            if not same_content:
                raise ProviderOutputError(
                    self.name,
                    f"conflicting proposals target the same path {proposal.target_path!r}",
                    payload_hash=payload_hash,
                )

            existing.provenance = self._unique_strings(existing.provenance + proposal.provenance)
            if proposal.confidence > existing.confidence or (
                proposal.confidence == existing.confidence and proposal.id < existing.id
            ):
                existing.summary = proposal.summary
                existing.snippet = proposal.snippet
                existing.confidence = proposal.confidence
                existing.notes = proposal.notes
            elif not existing.notes and proposal.notes:
                existing.notes = proposal.notes
        return deduped

    @staticmethod
    def _unique_strings(values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            item = value.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered

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
                lines.append(f"  - Confidence: {proposal.confidence:.2f}")
                lines.append(f"  - Snippet: {proposal.snippet}")
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
        return self._finalize_payload(payload, sources, payload_hash=text_sha256(text))

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

    def _finalize_payload(
        self,
        payload: dict[str, object],
        sources: list[SourceSnapshot],
        *,
        payload_hash: str,
    ) -> tuple[str, list[DreamProposal], list[str]]:
        report = str(payload.get("report", "# Hermes Dreaming Report\n\nNo report provided.\n"))
        proposals_value = payload.get("proposals", [])
        if proposals_value is None:
            proposals_value = []
        if not isinstance(proposals_value, list):
            raise ProviderOutputError(self.name, "proposals must be a list", payload_hash=payload_hash)
        source_refs = self._source_refs(sources)
        proposals = [
            self._normalize_proposal(item, source_refs=source_refs, payload_hash=payload_hash)
            for item in proposals_value
        ]
        proposals = self._dedupe_proposals(proposals, payload_hash=payload_hash)
        validation_errors = validate_proposals(proposals)
        if validation_errors:
            raise ProviderOutputError(self.name, "; ".join(validation_errors), payload_hash=payload_hash)
        notes = self._normalize_notes(payload.get("notes", []))
        return report, proposals, notes

    def _normalize_notes(self, value: object) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        return [str(value)]

    @staticmethod
    def _source_refs(sources: list[SourceSnapshot]) -> set[str]:
        refs: set[str] = set()
        for source in sources:
            for line_number in range(1, source.line_count + 1):
                refs.add(f"{Path(source.path).name}:{line_number}")
        return refs

    def _normalize_proposal(self, value: object, *, source_refs: set[str], payload_hash: str) -> DreamProposal:
        if not isinstance(value, dict):
            raise ProviderOutputError(self.name, "each proposal must be a JSON object", payload_hash=payload_hash)

        required = [
            "id",
            "target_kind",
            "target_path",
            "mode",
            "summary",
            "proposed_text",
            "confidence",
            "snippet",
            "provenance",
            "risk",
            "priority",
            "reason",
            "source_quote",
            "policy_flags",
        ]
        missing = [key for key in required if key not in value]
        if missing:
            raise ProviderOutputError(
                self.name,
                f"proposal is missing required field(s): {', '.join(sorted(missing))}",
                payload_hash=payload_hash,
            )

        def require_string(key: str) -> str:
            raw = value.get(key)
            if not isinstance(raw, str):
                raise ProviderOutputError(
                    self.name,
                    f"proposal {key} must be a string",
                    payload_hash=payload_hash,
                )
            text = raw.strip()
            if not text:
                raise ProviderOutputError(
                    self.name,
                    f"proposal {key} must be non-empty",
                    payload_hash=payload_hash,
                )
            return text

        proposed_text = require_string("proposed_text")

        confidence_value = value.get("confidence")
        if not isinstance(confidence_value, (int, float)):
            raise ProviderOutputError(self.name, "proposal confidence must be numeric", payload_hash=payload_hash)
        confidence = float(confidence_value)
        if confidence < 0.0 or confidence > 1.0:
            raise ProviderOutputError(
                self.name,
                f"proposal confidence {confidence!r} is outside 0.0-1.0",
                payload_hash=payload_hash,
            )

        provenance_value = value.get("provenance")
        if isinstance(provenance_value, str):
            provenance = [provenance_value.strip()] if provenance_value.strip() else []
        elif isinstance(provenance_value, list):
            provenance = []
            for item in provenance_value:
                if not isinstance(item, str):
                    raise ProviderOutputError(self.name, "proposal provenance entries must be strings", payload_hash=payload_hash)
                entry = item.strip()
                if entry:
                    provenance.append(entry)
        else:
            provenance = []
        if not provenance:
            raise ProviderOutputError(self.name, "proposal provenance must be non-empty", payload_hash=payload_hash)
        invalid_refs = sorted(ref for ref in provenance if ref not in source_refs)
        if invalid_refs:
            raise ProviderOutputError(
                self.name,
                f"proposal provenance must reference the source bundle: {', '.join(invalid_refs)}",
                payload_hash=payload_hash,
            )

        snippet = require_string("snippet")
        risk = require_string("risk").lower()
        if risk not in {"low", "medium", "high"}:
            raise ProviderOutputError(self.name, f"proposal risk {risk!r} is unsupported", payload_hash=payload_hash)
        priority = require_string("priority").lower()
        if priority not in {"low", "normal", "high"}:
            raise ProviderOutputError(self.name, f"proposal priority {priority!r} is unsupported", payload_hash=payload_hash)
        policy_flags_value = value.get("policy_flags")
        if not isinstance(policy_flags_value, list) or not all(isinstance(item, str) and item.strip() for item in policy_flags_value):
            raise ProviderOutputError(self.name, "proposal policy_flags must be a non-empty string list", payload_hash=payload_hash)
        policy_flags = [item.strip() for item in policy_flags_value]

        return DreamProposal.from_dict(
            {
                "id": require_string("id"),
                "target_kind": require_string("target_kind"),
                "target_path": require_string("target_path"),
                "mode": require_string("mode"),
                "summary": require_string("summary"),
                "provenance": provenance,
                "proposed_text": proposed_text,
                "approved": False,
                "confidence": confidence,
                "snippet": snippet,
                "risk": risk,
                "priority": priority,
                "reason": require_string("reason"),
                "source_quote": require_string("source_quote"),
                "policy_flags": policy_flags,
                "notes": value.get("notes"),
            }
        )

    def _dedupe_proposals(self, proposals: list[DreamProposal], *, payload_hash: str) -> list[DreamProposal]:
        deduped: list[DreamProposal] = []
        by_target: dict[str, DreamProposal] = {}
        for proposal in sorted(proposals, key=lambda item: (item.target_kind, item.target_path, item.mode, item.id)):
            existing = by_target.get(proposal.target_path)
            if existing is None:
                by_target[proposal.target_path] = proposal
                deduped.append(proposal)
                continue

            same_content = (
                existing.target_kind == proposal.target_kind
                and existing.mode == proposal.mode
                and existing.proposed_text == proposal.proposed_text
            )
            if not same_content:
                raise ProviderOutputError(
                    self.name,
                    f"conflicting proposals target the same path {proposal.target_path!r}",
                    payload_hash=payload_hash,
                )

            existing.provenance = self._unique_strings(existing.provenance + proposal.provenance)
            if proposal.confidence > existing.confidence or (
                proposal.confidence == existing.confidence and proposal.id < existing.id
            ):
                existing.summary = proposal.summary
                existing.snippet = proposal.snippet
                existing.confidence = proposal.confidence
                existing.notes = proposal.notes
            elif not existing.notes and proposal.notes:
                existing.notes = proposal.notes
        return deduped

    @staticmethod
    def _unique_strings(values: list[str]) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for value in values:
            item = value.strip()
            if not item or item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered

    def _build_prompt(self, sources: list[SourceSnapshot], context: DreamContext) -> str:
        source_block = "\n\n".join(f"### {Path(source.path).name}\n{source.content}" for source in sources)
        return (
            "You are Hermes Dreaming, a staged self-improvement engine.\n"
            "Return JSON only with keys: report, proposals, notes.\n"
            "Each proposal must include id, target_kind, target_path, mode, summary, provenance, confidence, snippet, proposed_text, approved, risk, priority, reason, source_quote, policy_flags.\n"
            "Risk must be one of low, medium, high. Priority must be one of low, normal, high.\n"
            "Reason must explain why the proposal exists. Source_quote must be a short quote from the source. Policy_flags must be a string list.\n"
            "Confidence must be a number between 0.0 and 1.0. Snippet must be the source quote or line that justifies the proposal.\n"
            "Provenance must be one or more source refs such as path:line.\n"
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
        return self._finalize_payload(payload, sources, payload_hash=text_sha256(text))


def build_provider(name: str, *, model: str | None = None, api_key: str | None = None, base_url: str | None = None) -> DreamProvider:
    normalized = name.lower().strip()
    if normalized in {"offline", "offline-marker", "marker"}:
        return OfflineMarkerProvider()
    if normalized in {"openai", "openai-compatible"}:
        return OpenAICompatibleProvider(model=model or "gpt-4o-mini", api_key=api_key, base_url=base_url)
    if normalized in {"ollama", "ollama-native"}:
        return OllamaProvider(model=model or "qwen2.5:3b", api_key=api_key, base_url=base_url or "http://127.0.0.1:11434")
    raise ValueError(f"unknown provider: {name}")


@dataclass(slots=True, frozen=True)
class ProviderInfo:
    name: str
    kind: str
    status: str  # always | optional | missing
    notes: str


def _openai_compat_available() -> bool:
    try:
        import openai  # noqa: F401

        return True
    except ImportError:
        return False


def list_providers() -> list[ProviderInfo]:
    """Return availability information for the built-in providers.

    The check is import-based: ``status=optional`` means the optional
    dependency is importable; ``status=missing`` means it is not. We do NOT
    ping external services (ollama server, etc.) from this command.
    """
    rows: list[ProviderInfo] = [
        ProviderInfo(
            name="offline-marker",
            kind="offline",
            status="always",
            notes="no API key required",
        ),
        ProviderInfo(
            name="openai-compatible",
            kind="openai_compat",
            status="optional" if _openai_compat_available() else "missing",
            notes="requires [llm] extra (openai package)",
        ),
        ProviderInfo(
            name="ollama",
            kind="ollama",
            status="optional",
            notes="requires local Ollama server and qwen2.5:3b (or override --model)",
        ),
    ]
    return rows


def render_providers_table(rows: list[ProviderInfo]) -> str:
    headers = ("NAME", "KIND", "STATUS", "NOTES")
    data = [(r.name, r.kind, r.status, r.notes) for r in rows]
    widths = [max(len(headers[i]), max(len(row[i]) for row in data)) for i in range(len(headers))]
    line = lambda values: "  ".join(value.ljust(widths[i]) for i, value in enumerate(values))
    lines = [line(headers), line(tuple("-" * w for w in widths))]
    for row in data:
        lines.append(line(row))
    return "\n".join(lines) + "\n"
