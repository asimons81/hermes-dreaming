---
name: hermes-dreaming
description: Use when Hermes needs staged self-improvement, explicit reviewable artifacts, or safe apply/discard workflows for memory, user, skill, or fact updates.
---

# Hermes Dreaming

Use this plugin when you want staged, reviewable self-improvement instead of silent writes.

## Core idea

Hermes-dreaming scans explicit source inputs, stages proposed changes in an artifact directory, and only writes to live state after an explicit apply step. It is designed for local-first, reviewable updates.

## When to use

- You want to convert notes or `DREAM:` markers into staged proposals.
- You want a reviewable diff before anything touches live state.
- You want explicit apply/discard gates.
- You want to keep backups and archives under separate roots.

## Main commands

```bash
dreaming create --live-root ./live --artifact-root ./artifacts --source ./sources
dreaming review --live-root ./live --artifact-root ./artifacts --source ./sources
dreaming diff ./artifacts/<artifact-id> --live-root ./live
dreaming validate ./artifacts/<artifact-id> --live-root ./live
dreaming apply ./artifacts/<artifact-id> --live-root ./live --backup-root ./backups --approve all
dreaming discard ./artifacts/<artifact-id> --archive-root ./archive
dreaming compact --artifact-root ./artifacts --archive-root ./archive
dreaming install-cron --schedule "0 3 * * *"
dreaming status --artifact-root ./artifacts
dreaming update
```

## Safe usage pattern

1. Keep the live root small and explicit.
2. Put generated artifacts in a separate artifact root.
3. Use `diff` and `validate` before `apply`.
4. Use `apply` only after human approval.
5. Use `discard` when the staged proposal is wrong or stale.

## Fast path

If you want the safest short workflow, use `review` first, then `diff`, `validate`, and `apply` only after the staged artifact looks right.

## Dream marker format

The offline provider looks for explicit `DREAM:` lines in the source bundle.

```text
DREAM: memory: Keep updates short and concrete.
DREAM: user: Prefer concise status updates.
DREAM: fact: {"type": "preference", "key": "tone", "value": "casual"}
DREAM: skill: path=skills/review.md | Preserve review gates and backups.
```

## Notes

- This plugin is local-first and does not need paid X or cloud APIs for the default offline flow.
- Use the optional LLM provider only if you explicitly want one.
- The plugin is fine without this skill file, but the skill makes the workflow much easier to remember and reuse.
