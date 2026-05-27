# Changelog

## Unreleased

- Added a safe `dreaming update` command for fast-forward plugin updates with dirty-tree protection and optional pytest verification.
- Added a proper Hermes plugin wrapper so the repo can install as `hermes-dreaming`.
- Bundled a Hermes skill for the staged self-improvement workflow.
- Added an install-time handoff note for the Hermes plugin path.

## 0.1.0 — 2026-05-25

- Added the Hermes Dreaming artifact-first MVP.
- Added `create`, `diff`, `validate`, `apply`, `discard`, and `status` commands.
- Added directory-based dream artifacts with `manifest.json`, `REPORT.md`, `sources.jsonl`, and `proposals.jsonl`.
- Added validation, backups, and discard/archive semantics.
- Added offline marker parsing plus an optional OpenAI-compatible provider.
- Added tests for the core model, validation, CLI flow, and apply/discard behavior.
- Added initial scaffold and repository setup.
