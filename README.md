# hermes-dreaming

A standalone, open-source implementation of the Hermes Dreaming contract.

Hermes Dreaming stages proposed changes in an artifact directory first, then applies them only after an explicit approve/apply step. The MVP is intentionally boring: no silent writes, no hidden background mutation, and no hardcoded personal paths.

## What it does

- reads configured source files or directories
- scans for deterministic `DREAM:` markers in session-style text
- stages memory, user, skill, and fact proposals in an artifact directory
- validates paths, provenance, and secret-like content before apply
- applies approved proposals with backups
- discards staged artifacts without touching live files

## CLI

```bash
dreaming create --live-root ./live --artifact-root ./artifacts --source ./sources
dreaming diff ./artifacts/<artifact-id>
dreaming validate ./artifacts/<artifact-id> --live-root ./live
dreaming apply ./artifacts/<artifact-id> --live-root ./live --backup-root ./backups --approve all
dreaming discard ./artifacts/<artifact-id> --archive-root ./archive
dreaming status --artifact-root ./artifacts
```

## Dream marker format

The offline MVP provider looks for lines like:

```text
DREAM: memory: Keep updates short and concrete.
DREAM: user: Prefer concise status updates.
DREAM: fact: {"type": "preference", "key": "tone", "value": "casual"}
DREAM: skill: path=skills/review.md | Preserve review gates and backups.
```

## Artifact layout

Each run writes a staged artifact directory containing:

- `manifest.json`
- `REPORT.md`
- `sources.jsonl`
- `proposals.jsonl`

The artifact is intentionally simple, deterministic, and easy to review in git or on disk.

## Development

```bash
pytest -q
python -m build --wheel
```

The repo is intentionally self-contained and safe for public release review.
