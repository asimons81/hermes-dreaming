# Hermes Dreaming MVP Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a safe, reviewable self-improvement engine that turns recent session/context data into staged dream artifacts, then applies only explicitly approved changes to memory, skills, and fact-store targets.

**Architecture:** Keep the CLI thin and make the engine artifact-first. The core package owns deterministic proposal generation, schema validation, diff rendering, explicit apply/discard semantics, and post-writeback verification. All stateful writes go through allowlisted target adapters, and the only persisted outputs are immutable dream artifacts plus apply/discard receipts.

**Tech Stack:** Python 3.11, `argparse`, `dataclasses`, `pathlib`, `json`, `hashlib`, `pytest`.

---

## 1) Current state and what research changed

Current scaffold:
- `README.md` documents the contract at a high level.
- `pyproject.toml` exposes a single `dreaming` console script.
- `src/hermes_dreaming/cli.py` only supports a `status` command.
- `tests/test_smoke.py` only verifies the version and status output.

Research result from `research/upstream-overlap.md` changes the implementation shape in one important way: this repo should not try to be another user-facing Dreaming/reflection mode or background auto-dream pipeline. Upstream already has that terrain covered. The standalone repo should be the safe artifact/apply contract itself.

That means the MVP is artifact-centric, explicit, and synchronous. No hidden scheduler. No silent live mutation. No automatic consolidation/pruning loop.

---

## 2) Feature scope and non-goals

### In scope
- Read session/context input from explicit local inputs or imported snapshots.
- Produce a deterministic staged dream artifact with provenance.
- Render a human-reviewable diff before any writeback.
- Apply only allowlisted changes to memory, skill, and fact-store targets.
- Discard artifacts without mutating live state.
- Verify the post-writeback state and persist an apply/discard receipt.

### Non-goals for MVP
- Background/idle dreaming.
- Auto-apply or auto-prune behavior.
- Gateway/UI integration.
- Live direct writes during analysis.
- Hidden mutation paths.
- Repo secret handling, token capture, or private operational data ingestion.
- General-purpose sync across arbitrary external systems.

### Contract adjustment after research
The original brief can stay conceptually the same, but the MVP wording should be tightened to:
- staged dream artifact flow, not “dream mode”
- explicit apply/discard, not implicit background action
- snapshot/import based inputs, not live daemon coupling
- allowlisted target adapters only
- deterministic artifacts with provenance and verification receipts

---

## 3) Target package layout

Keep the package flat and readable. Don’t bury the MVP in nested subpackages.

### Source files to add
- `src/hermes_dreaming/models.py`
  - Dataclasses for `DreamArtifact`, `DreamChange`, `DreamProvenance`, `ApplyReceipt`, and `ValidationResult`.
  - Why: one place for schema-shaped data and round-trip tests.

- `src/hermes_dreaming/artifact.py`
  - JSON serialization, canonical hashing, artifact load/save helpers, and schema versioning.
  - Why: artifact format should be independent of CLI plumbing.

- `src/hermes_dreaming/targets.py`
  - Allowlisted target adapter protocol and concrete adapters for memory, skills, and fact-store.
  - Why: apply/discard must not talk to arbitrary paths or stores directly.

- `src/hermes_dreaming/engine.py`
  - Proposal generation, diff rendering, apply/discard orchestration, and verification workflow.
  - Why: this is the core behavior the tests should exercise.

- `src/hermes_dreaming/cli.py`
  - CLI parsing and output only.
  - Why: keep business logic out of argument parsing.

### Files to update
- `pyproject.toml`
  - Add any new optional dev/test dependencies if needed.
  - Keep the console script at `dreaming`.

- `README.md`
  - Replace the current generic scaffold text with command-level usage and the explicit safety model.

- `tests/test_smoke.py`
  - Expand or split into command and artifact tests.

### New test files to add
- `tests/test_models.py`
- `tests/test_artifact.py`
- `tests/test_engine.py`
- `tests/test_cli.py`
- `tests/test_targets.py`
- `tests/test_safety.py`

### Repo structure change that is worth making
- Add `specs/` as the canonical doc/contract folder.
- Add `var/` or `.hermes-dreaming/` as the runtime output root for generated artifacts and receipts, and gitignore it.

Why: the repo needs a clean separation between checked-in contract docs and ephemeral runtime outputs.

---

## 4) Command surface for MVP

Keep the command surface small and explicit.

### `dreaming status`
Purpose: quick scaffold/health check and current contract summary.

### `dreaming propose`
Purpose: generate a staged artifact from explicit input bundles.
Suggested flags:
- `--input <path>` — required input bundle or snapshot file
- `--output <path>` — artifact destination, defaults to runtime output root
- `--subject <name>` — optional label for the proposal
- `--format json|md` — artifact sidecar rendering, if supported

Expected behavior:
- deterministically generate the same artifact for the same input bundle
- write an immutable artifact file
- print the artifact id and hash

### `dreaming diff`
Purpose: render the proposed changes for review.
Suggested flags:
- `--artifact <path>` — required
- `--color/--no-color`

Expected behavior:
- read-only
- no mutation
- show target-by-target changes plus provenance

### `dreaming apply`
Purpose: apply a reviewed artifact to live targets.
Suggested flags:
- `--artifact <path>` — required
- `--yes` — explicit confirmation
- `--target-root <path>` — only if the MVP uses local target snapshots

Expected behavior:
- validate the artifact before any write
- refuse unknown target types
- write changes through adapters only
- verify the post-writeback state
- emit an apply receipt

### `dreaming discard`
Purpose: record that an artifact was reviewed and rejected.
Suggested flags:
- `--artifact <path>` — required
- `--reason <text>` — required
- `--yes`

Expected behavior:
- no writeback to live targets
- mark the artifact as discarded in its receipt trail
- keep the original artifact immutable

### `dreaming verify`
Purpose: check that an artifact’s expected post-state matches actual state.
Suggested flags:
- `--artifact <path>` — required
- `--target-root <path>` if applicable

Expected behavior:
- read-only verification
- report mismatches clearly
- exit non-zero on drift

---

## 5) Artifact format

Use a directory-based artifact with a single canonical manifest plus sidecar review files.

### Artifact directory
- Suggested default: `dream-<artifact_id>/`
- Stored under the runtime output root, not in source control.

### Required files
- `manifest.json` — canonical machine-readable state
- `REPORT.md` — human-readable summary
- `sources.jsonl` — source provenance snapshots
- `proposals.jsonl` — structured proposal records

### Required manifest fields
- `artifact_id`
- `created_at`
- `provider`
- `status` (`staged`, `applied`, `discarded`, `invalid`)
- `workspace_root`
- `source_roots`
- `report`
- `sources`
- `proposals`
- `notes` if the provider has extra commentary
- `validation_errors` if the artifact was marked invalid during creation
- `applied_at` / `discarded_at` when relevant

### Required per-change fields
- `id`
- `target_kind` (`memory`, `user`, `skill`, `fact`)
- `target_path`
- `mode` (`append_text`, `jsonl_append`)
- `summary`
- `provenance`
- `proposed_text`
- `approved`

### Receipt fields
Every apply/discard action should produce a receipt with:
- `artifact_id`
- `action`
- `timestamp`
- `actor`
- `result`
- `verification_summary`
- `error` if applicable

### Why this shape
- deterministic hashing is still easy
- schema validation is straightforward
- test fixtures are simple
- humans can still review a rendered diff/markdown preview if needed

Optional later: generate a companion markdown preview, but the directory manifest stays canonical.

---

## 6) Apply/discard semantics

### Apply
Apply must behave like a guarded transaction, even if the underlying targets are not truly transactional.

Rules:
1. Validate the artifact first.
2. Refuse to proceed if the artifact hash or schema is invalid.
3. Refuse unknown target types.
4. Capture pre-apply snapshots for any target adapter that supports restore.
5. Apply one change set at a time through the adapter interface.
6. Verify the live state after each target batch or at the end, depending on the adapter.
7. If verification fails, mark the receipt failed and attempt rollback where possible.
8. If rollback is partial or impossible, stop and surface the exact broken target.

### Discard
Discard is explicit and final for the review cycle.

Rules:
1. No live-state mutation.
2. Persist a discard receipt with the reason.
3. Leave the artifact immutable.
4. Make discard idempotent, so repeating it does not create duplicate side effects.

### Idempotency
- Applying the same artifact twice should either be a no-op or fail loudly with “already applied,” depending on adapter support.
- Discarding the same artifact twice should be safe and should not mutate live state.

### Conflict handling
If the live state changed since proposal generation, apply must fail with a conflict unless the change is still semantically safe and explicitly allowed by the adapter policy.

---

## 7) Validation and safety gates

These gates are mandatory before any writeback.

1. **Schema validation**
   - Required fields present.
   - Unknown target types rejected.
   - Schema version supported.

2. **Deterministic hash check**
   - Recompute `content_hash` from the canonical JSON serialization.
   - Reject mismatches.

3. **Provenance completeness**
   - Every change must cite source references.
   - Missing provenance blocks apply.

4. **Allowlist enforcement**
   - Only `memory`, `skill`, and `fact_store` targets are allowed in MVP.
   - No arbitrary filesystem writes.

5. **Sensitive-data filter**
   - Reject artifacts that contain obvious secrets, tokens, or private operational data.
   - The safe default is to refuse rather than redact silently.

6. **Review gate**
   - `apply` requires explicit human confirmation.
   - No hidden auto-approval.

7. **Post-writeback verification**
   - Read the target back after apply.
   - Report drift or partial application.

8. **Receipt persistence**
   - Every apply/discard attempt leaves an auditable receipt.

---

## 8) Implementation sequence

### Task 1: Define the artifact and receipt models
- Add `models.py`.
- Write tests for dataclass shape, serialization-friendly fields, and hash stability.
- Goal: a stable schema before any CLI work.

### Task 2: Implement artifact serialization and canonical hashing
- Add `artifact.py`.
- Write tests for round-trip load/save, stable hash output, and unsupported schema rejection.
- Goal: make artifacts immutable and reviewable.

### Task 3: Add target adapters and safety allowlist
- Add `targets.py`.
- Write tests for allowed target types, blocked target types, and no arbitrary path writes.
- Goal: prevent accidental broad write access.

### Task 4: Build the proposal and diff engine
- Add `engine.py`.
- Write tests for deterministic proposal generation and readable diffs.
- Goal: same inputs must produce same artifact.

### Task 5: Implement apply/discard/verify workflow
- Extend `engine.py` and `cli.py`.
- Write tests for apply success, apply failure, rollback behavior, discard idempotency, and post-apply verification.
- Goal: explicit writeback with receipts.

### Task 6: Expand the CLI surface
- Wire `status`, `propose`, `diff`, `apply`, `discard`, and `verify` into `cli.py`.
- Write CLI tests for exit codes, required flags, and output text.
- Goal: make the contract usable from the shell.

### Task 7: Update docs and fixtures
- Update `README.md` with usage examples.
- Add sample fixtures under `tests/fixtures/`.
- Add the plan file under `specs/` if not already present.

---

## 9) Test matrix

| Area | Test file | What it proves |
|---|---|---|
| Data model | `tests/test_models.py` | Dataclasses serialize cleanly and include the required fields |
| Artifact IO | `tests/test_artifact.py` | Save/load round-trip works and canonical hash is stable |
| Safety | `tests/test_safety.py` | Unknown targets, secrets, and malformed artifacts are rejected |
| Engine proposal | `tests/test_engine.py` | Proposal generation is deterministic for identical inputs |
| Diff rendering | `tests/test_engine.py` | Human review output matches the proposed changes |
| Apply success | `tests/test_engine.py` | Approved artifacts mutate only allowlisted targets and verify cleanly |
| Apply failure | `tests/test_engine.py` | Partial failure surfaces clearly and triggers rollback attempts |
| Discard semantics | `tests/test_engine.py` | Discard is explicit, idempotent, and non-mutating |
| CLI behavior | `tests/test_cli.py` | Commands parse correctly and exit codes are correct |
| Smoke path | `tests/test_smoke.py` | The package still exposes version/status and the CLI boots |

Minimum acceptance for MVP:
- artifact round-trip tests pass
- at least one deterministic proposal test passes
- apply/discard tests pass
- safety rejection tests pass
- CLI smoke passes

---

## 10) Risks and open questions

1. **Live Hermes integration is not part of the MVP**
   - The standalone repo should use explicit input bundles or exported snapshots first.
   - If live adapters are added later, they should sit behind the same target interface.

2. **Rollback may be partial**
   - Some target stores may not support exact undo.
   - The plan should prefer fail-closed behavior and explicit failure receipts over pretending the write was atomic.

3. **Artifact provenance can get noisy**
   - Keep provenance specific but bounded.
   - Don’t dump raw private context into the artifact.

4. **Scope creep into auto-dreaming**
   - Don’t let background scheduling, auto-prune, or review routing creep into v1.
   - Those are separate products, not the core contract.

---

## 11) Success definition for implementation

The MVP is done when:
- `dreaming propose` creates a deterministic artifact.
- `dreaming diff` makes the proposal reviewable.
- `dreaming apply` writes only through allowlisted adapters and verifies the result.
- `dreaming discard` is explicit and non-mutating.
- Invalid or secret-looking proposals are rejected.
- All important behaviors are covered by tests.
- The repository stays cleanly scoped as a staged artifact engine, not a background Dreaming clone.
