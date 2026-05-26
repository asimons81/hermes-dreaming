# hermes-dreaming

![Hermes Dreaming hero banner](assets/readme/hermes-dreaming-hero.png)

A standalone, open-source staged self-improvement engine for Hermes-style memory, user, skill, and fact updates.
It scans explicit source inputs, stages proposed changes in a reviewable artifact directory, and only writes to live state after an explicit apply step.

## Hermes plugin

This repo now ships as a proper Hermes plugin too.

Install from a git checkout with:

```bash
hermes plugins install file:///path/to/hermes-dreaming --enable
```

Once installed, use:

```bash
hermes dreaming --help
```

The plugin also bundles a Hermes skill for the staged review workflow as `hermes-dreaming:dreaming`.

## Current status

- Artifact-first MVP is implemented
- Apply and discard are explicit
- Tests pass locally
- Hermes plugin wrapper is included

## Install

For local development:

```bash
python -m pip install -e .[dev]
```

If you want the optional OpenAI-compatible provider:

```bash
python -m pip install -e .[llm]
```

## CLI

```bash
dreaming create --live-root ./live --artifact-root ./artifacts --source ./sources
dreaming diff ./artifacts/<artifact-id>
dreaming validate ./artifacts/<artifact-id> --live-root ./live
dreaming apply ./artifacts/<artifact-id> --live-root ./live --backup-root ./backups --approve all
dreaming discard ./artifacts/<artifact-id> --archive-root ./archive
dreaming status --artifact-root ./artifacts
```

## Dream markers

The offline provider looks for explicit `DREAM:` lines in the source bundle.

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

The artifact is intentionally simple, deterministic, and easy to review on disk or in git.

## Repo docs

- `brief.md` has the project brief and non-goals
- `specs/mvp-implementation-plan.md` describes the current implementation contract and package layout
- `docs/release-checklist.md` is the pre-release checklist
- `reviews/final-sanity.md` records the most recent QA pass

## Development

```bash
pytest -q
python -m pip install build
python -m build --wheel
```

The repo is intentionally self-contained and safe for public release review.
