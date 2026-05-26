from __future__ import annotations

import sys
import types
from pathlib import Path

from hermes_dreaming.artifact import SourceSnapshot
from hermes_dreaming.providers import DreamContext, OllamaProvider, OpenAICompatibleProvider, build_provider


class _FakeResponses:
    def __init__(self, text: str) -> None:
        self._text = text

    def create(self, **_kwargs):
        return types.SimpleNamespace(output_text=self._text)


class _FakeOpenAI:
    output_text = ""

    def __init__(self, **_kwargs) -> None:
        self.responses = _FakeResponses(self.output_text)


def _install_fake_openai(monkeypatch, text: str) -> None:
    _FakeOpenAI.output_text = text
    fake_module = types.SimpleNamespace(OpenAI=_FakeOpenAI)
    monkeypatch.setitem(sys.modules, "openai", fake_module)


def _context(tmp_path: Path) -> DreamContext:
    return DreamContext(
        workspace_root=tmp_path,
        live_root=tmp_path / "live",
        artifact_dir=tmp_path / "artifact",
        source_roots=[tmp_path / "sources"],
        model="qwen2.5:3b",
    )


def _source() -> SourceSnapshot:
    return SourceSnapshot(
        path="sources/session.md",
        kind="file",
        content="User: Prefer two strong options over six weak ones.",
        sha256="abc123",
        line_count=1,
    )


def test_openai_compatible_provider_accepts_fenced_json_and_forces_unapproved(monkeypatch, tmp_path: Path) -> None:
    _install_fake_openai(
        monkeypatch,
        """```json
{
  "report": "Report body",
  "proposals": [
    {
      "id": 1,
      "target_kind": "user",
      "target_path": "user.md",
      "mode": "append_text",
      "summary": "User prefers two strong options.",
      "provenance": "sources/session.md:1",
      "proposed_text": "- Restaurant design drafts should offer two strong options, not six weak ones.",
      "approved": true
    }
  ],
  "notes": "scalar note"
}
```""",
    )

    report, proposals, notes = OpenAICompatibleProvider(model="qwen2.5:3b", api_key="ollama").generate(
        [_source()], _context(tmp_path)
    )

    assert report == "Report body"
    assert notes == ["scalar note"]
    assert len(proposals) == 1
    assert proposals[0].id == "1"
    assert proposals[0].provenance == ["sources/session.md:1"]
    assert proposals[0].approved is False


def test_openai_compatible_provider_drops_invalid_model_proposals(monkeypatch, tmp_path: Path) -> None:
    _install_fake_openai(
        monkeypatch,
        """{
  "report": "Report body",
  "proposals": [
    {
      "id": "missing-text",
      "target_kind": "user",
      "target_path": "user.md",
      "mode": "append_text",
      "summary": "No text should be staged.",
      "provenance": "sources/session.md:1",
      "approved": true
    },
    {
      "id": "valid",
      "target_kind": "memory",
      "target_path": "memory.md",
      "mode": "append_text",
      "summary": "Keep concise.",
      "provenance": ["sources/session.md:1"],
      "proposed_text": "- Keep concise.",
      "approved": false
    }
  ],
  "notes": null
}""",
    )

    _report, proposals, notes = OpenAICompatibleProvider(model="qwen2.5:3b", api_key="ollama").generate(
        [_source()], _context(tmp_path)
    )

    assert [proposal.id for proposal in proposals] == ["valid"]
    assert notes == []


def test_openai_compatible_provider_defaults_missing_provenance_to_sources(monkeypatch, tmp_path: Path) -> None:
    _install_fake_openai(
        monkeypatch,
        """{
  "report": "Report body",
  "proposals": [
    {
      "id": "valid",
      "target_kind": "user",
      "target_path": "user.md",
      "mode": "append_text",
      "summary": "User prefers two strong options.",
      "proposed_text": "- Prefer two strong options over six weak ones.",
      "approved": true
    }
  ],
  "notes": []
}""",
    )

    _report, proposals, _notes = OpenAICompatibleProvider(model="qwen2.5:3b", api_key="ollama").generate(
        [_source()], _context(tmp_path)
    )

    assert len(proposals) == 1
    assert proposals[0].provenance == ["sources/session.md"]
    assert proposals[0].approved is False


def test_ollama_provider_uses_native_json_chat(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self) -> bytes:
            return b'{"message":{"content":"{\\"report\\":\\"Report body\\",\\"proposals\\":[{\\"id\\":\\"p1\\",\\"target_kind\\":\\"user\\",\\"target_path\\":\\"user.md\\",\\"mode\\":\\"append_text\\",\\"summary\\":\\"Keep concise.\\",\\"provenance\\":\\"sources/session.md:1\\",\\"proposed_text\\":\\"- Keep concise.\\",\\"approved\\":true}],\\"notes\\":[]}"}}'

    def _fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = request.data.decode("utf-8")
        captured["timeout"] = timeout
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    report, proposals, notes = OllamaProvider(model="qwen2.5:3b", base_url="http://ollama.test").generate(
        [_source()], _context(tmp_path)
    )

    assert captured["url"] == "http://ollama.test/api/chat"
    assert '"format": "json"' in captured["body"]
    assert '"stream": false' in captured["body"]
    assert report == "Report body"
    assert notes == []
    assert len(proposals) == 1
    assert proposals[0].approved is False
    assert proposals[0].provenance == ["sources/session.md:1"]


def test_build_provider_supports_ollama() -> None:
    provider = build_provider("ollama", model="qwen2.5:3b")

    assert isinstance(provider, OllamaProvider)
    assert provider.model == "qwen2.5:3b"
