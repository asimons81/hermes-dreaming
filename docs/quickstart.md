# Hermes Dreaming quickstart

This demo is offline. It uses the default `offline-marker` provider, so no API key or external model access is required.

## Fixture paths

- Live root: `examples/quickstart/live`
- Source root: `examples/quickstart/sources`
- Artifact root: `${TMPDIR:-/tmp}/hermes-dreaming-quickstart/artifacts`
- Backup root: `${TMPDIR:-/tmp}/hermes-dreaming-quickstart/backups`

## Copy/paste demo

Run this from the repository root.

If the `dreaming` entrypoint is not installed yet, replace it with `python -m hermes_dreaming` in the commands below.

```bash
export DEMO_ROOT="$(pwd)/examples/quickstart"
export LIVE_ROOT="$DEMO_ROOT/live"
export SOURCE_ROOT="$DEMO_ROOT/sources"
export ARTIFACT_ROOT="${TMPDIR:-/tmp}/hermes-dreaming-quickstart/artifacts"
export BACKUP_ROOT="${TMPDIR:-/tmp}/hermes-dreaming-quickstart/backups"
export HERMES_DREAMING_STATE_ROOT="${TMPDIR:-/tmp}/hermes-dreaming-quickstart/state"
export REVIEW_LOG="${TMPDIR:-/tmp}/hermes-dreaming-quickstart-review.log"

mkdir -p "$ARTIFACT_ROOT" "$BACKUP_ROOT" "$HERMES_DREAMING_STATE_ROOT"

dreaming review \
  --live-root "$LIVE_ROOT" \
  --artifact-root "$ARTIFACT_ROOT" \
  --source "$SOURCE_ROOT" | tee "$REVIEW_LOG"

ARTIFACT_DIR="$(awk -F': ' '/^artifact: / {print $2; exit}' "$REVIEW_LOG")"

dreaming diff "$ARTIFACT_DIR" --live-root "$LIVE_ROOT"
dreaming validate "$ARTIFACT_DIR" --live-root "$LIVE_ROOT"
dreaming apply "$ARTIFACT_DIR" --live-root "$LIVE_ROOT" --backup-root "$BACKUP_ROOT" --approve all
dreaming status --artifact-root "$ARTIFACT_ROOT"
```

## What success looks like

`dreaming review` should print something close to:

```text
artifact: /tmp/hermes-dreaming-quickstart/artifacts/2026...-<id>
status: staged
proposals: 4
mode: dry-run
validation: valid
```

`dreaming diff` should start with `# Hermes Dreaming Diff` and then show one `## Proposal ...` block for each of these targets:

- `fact -> facts.jsonl`
- `memory -> memory.md`
- `skill -> skills/review.md`
- `user -> user.md`

`dreaming validate` should print `artifact is valid`.

`dreaming apply` should print `applied artifact: <id>` and `status: applied`.

`dreaming status` should finish with an `Artifact state: applied=1` line.

## Why this is offline

The fixture uses explicit `DREAM:` lines in text files. That means the default offline provider can generate proposals without any API key, model account, or network call. The walkthrough also points `HERMES_DREAMING_STATE_ROOT` at a temp directory so the demo does not touch your normal Dreaming run ledger.
