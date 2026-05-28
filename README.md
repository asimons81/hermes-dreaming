# hermes-dreaming

[![CI](https://github.com/asimons81/hermes-dreaming/actions/workflows/ci.yml/badge.svg)](https://github.com/asimons81/hermes-dreaming/actions/workflows/ci.yml)

![Hermes Dreaming hero banner](assets/readme/hermes-dreaming-hero.png)

A standalone, open-source staged self-improvement engine for Hermes-style memory, user, skill, and fact updates.
It scans explicit source inputs, stages proposed changes in a reviewable artifact directory, and only writes to live state after an explicit apply step.

## Hermes plugin

This repo now ships as a proper Hermes plugin too.

Install from GitHub with:

```bash
hermes plugins install asimons81/hermes-dreaming --enable
```

For a local checkout during development:

```bash
hermes plugins install file:///path/to/hermes-dreaming --enable
```

Once installed, use:

```bash
hermes dreaming review --help
```

Update the installed checkout with:

```bash
hermes dreaming update
```

Use `hermes dreaming update --check` if you only want the status check.

The plugin also bundles a Hermes skill named `dreaming`. Load that bare name inside Hermes if you want the guided staged workflow.

## Current status

- **Full feature set:** create, review, diff, validate, apply, discard, compact, install-cron, status, update, all implemented
- **Live memory mutation** with score gating, idempotence, backups, and capacity enforcement
- **Run ledger + DREAMS.md diary** for auditability
- **Hermes-native plugin:** install once, use everywhere
- **Recent-session reader** with fallback chain (SessionDB → SQLite → pointer-log)
- **Cron installer** for nightly dry-run review
- **Test suite passes locally**

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
# Create an artifact from sources
dreaming create --live-root ./live --artifact-root ./artifacts --source ./sources

# Review: create and validate without applying
dreaming review --live-root ./live --artifact-root ./artifacts --source ./sources

# Inspect an artifact
dreaming diff ./artifacts/<artifact-id> --live-root ./live

# Validate a staged artifact
dreaming validate ./artifacts/<artifact-id> --live-root ./live

# Apply approved changes (explicit approval required)
dreaming apply ./artifacts/<artifact-id> --live-root ./live --backup-root ./backups --approve all

# Discard a staged artifact
dreaming discard ./artifacts/<artifact-id> --archive-root ./archive

# Compact terminal (applied/discarded) artifacts to an archive
dreaming compact --artifact-root ./artifacts --archive-root ./archive

# Install a nightly review-only cron job
dreaming install-cron --schedule "0 3 * * *"

# Show artifact status
dreaming status --artifact-root ./artifacts

# Safely update the installed checkout
dreaming update
dreaming update --check
```

## Quickstart demo fixture

If you want the shortest path to "oh, I get it," use `examples/quickstart/`. It is an offline fixture, so no API key or external model access is required.
If the `dreaming` entrypoint is not installed yet, swap in `python -m hermes_dreaming` for the same commands.

- Fixture notes: `examples/quickstart/README.md`
- Runnable walkthrough: `docs/quickstart.md`

### Command notes

- `create` and `review` accept repeatable `--source` plus optional `--provider`, `--model`, `--api-key`, and `--base-url`.
- `diff` accepts optional `--live-root` and renders unified diffs when the live target root is available.
- `apply` accepts repeatable `--approve` values, including `all`.
- `update` supports `--remote`, `--branch`, `--check`, and `--no-verify`.

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

- `CONTRIBUTING.md` is the contributor guide and local workflow contract
- `SECURITY.md` covers private vulnerability reporting
- `CODE_OF_CONDUCT.md` sets the collaboration rules
- `brief.md` has the project brief and non-goals
- `specs/mvp-implementation-plan.md` describes the current implementation contract and package layout
- `docs/release-checklist.md` is the pre-release checklist
- `reviews/final-sanity.md` records the most recent QA pass
- `research/upstream-overlap.md` captures the upstream overlap notes and references

## Contributing

If you want to contribute, start with `CONTRIBUTING.md`.

- Use the issue templates so the scope and intent are clear.
- Run `pytest -q`, `python -m build --wheel`, and `git diff --check` before requesting review.
- If your change touches live roots, artifact roots, or writeback behavior, state that explicitly.
- If you change release-facing text or safety rules, make sure the docs still match shipped behavior.

## Development

```bash
pytest -q
python -m pip install build
python -m build --wheel
```

The repo is intentionally self-contained and safe for public release review.
