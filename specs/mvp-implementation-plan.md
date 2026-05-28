# Hermes Dreaming MVP Implementation Plan

## Purpose

Hermes Dreaming is a standalone, artifact-first self-improvement engine for staged memory, user, skill, and fact updates.

The repo has one job: read explicit local inputs, stage reviewable proposals, and apply only approved changes through a guarded write path.

## What shipped

The current MVP includes:

- `dreaming create`, `diff`, `validate`, `apply`, `discard`, and `status`
- a directory-based artifact format with `manifest.json`, `REPORT.md`, `sources.jsonl`, and `proposals.jsonl`
- deterministic offline proposal extraction from explicit `DREAM:` markers
- an optional OpenAI-compatible provider behind the `llm` extra
- validation for path safety, duplicate targets, provenance, and secret-like content
- backups before apply, plus explicit discard/archive behavior
- unit and integration tests for the data model, validation, CLI flow, and apply/discard semantics

## Scope and non-goals

### In scope
- explicit source bundles or imported snapshots
- staged artifact creation
- diff rendering for review
- guarded apply with backups
- discard without live mutation
- reproducible tests

### Out of scope
- background dreaming or idle-time auto consolidation
- implicit mutation during analysis
- gateway or dashboard integration
- broad sync to arbitrary external systems
- secret ingestion or private operational data capture

## Package layout

```text
src/hermes_dreaming/
├── __init__.py
├── __main__.py
├── analyze.py
├── apply.py
├── artifact.py
├── cli.py
├── collect.py
├── providers.py
└── validation.py
```

### Roles
- `artifact.py` owns the dataclasses, JSON serialization, and load/save helpers.
- `collect.py` turns explicit source roots into source snapshots.
- `providers.py` contains the offline marker parser and the optional OpenAI-compatible provider.
- `analyze.py` builds artifacts and renders diffs.
- `validation.py` blocks unsafe or malformed proposals.
- `apply.py` performs guarded apply and discard actions.
- `cli.py` stays thin and only handles argument parsing and output.

## Command surface

### `dreaming create`
Creates a staged artifact from one or more `--source` roots.

Defaults:
- `--live-root` defaults to the current directory
- `--artifact-root` defaults to `./.dreaming/artifacts`
- `--provider` defaults to `offline-marker`

### `dreaming diff`
Prints live-target unified diffs for each proposal when a live root is available, otherwise falls back to the staged report and proposal summary.

### `dreaming validate`
Runs the validation gate without mutating live state.

### `dreaming apply`
Applies approved proposals, writes backups first, and updates the artifact status.

### `dreaming discard`
Marks the artifact discarded and moves it into the archive root without touching live files.

### `dreaming status`
Lists known artifacts in the artifact root.

## Artifact format

Canonical artifact directory contents:

- `manifest.json` stores the machine-readable state
- `REPORT.md` stores the human-readable summary
- `sources.jsonl` stores source snapshots and provenance
- `proposals.jsonl` stores the staged proposal records

Required proposal fields:
- `id`
- `target_kind`
- `target_path`
- `mode`
- `summary`
- `provenance`
- `proposed_text`
- `approved`

Current supported proposal modes:
- `append_text`
- `jsonl_append`

## Validation and safety

The validation layer rejects or flags:

- target paths that escape the live root
- duplicate targets with conflicting payloads
- missing provenance
- secret-like content in source or proposal text
- malformed JSON payloads for JSONL append proposals
- live roots that do not exist

Apply is intentionally boring:

1. validate first
2. back up the target file if it exists
3. write the new content
4. update the artifact status to `applied`

Discard is intentionally boring too:

1. update the artifact status to `discarded`
2. move the artifact directory into the archive root
3. leave live files untouched

## Tests

- artifact round-trip coverage
- validation edge cases
- apply and discard behavior
- CLI command flow
- smoke coverage for the public package surface

## Release note

The repo is implemented and QA'd, but it is not released yet. Use `docs/release-checklist.md` before any tag, publish, or public handoff.
