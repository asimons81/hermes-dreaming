# hermes-dreaming

A standalone, open-source implementation of the **Hermes Dreaming** contract.

Dreaming is a staged self-improvement loop for Hermes-style agent memories and
skills. It reads recent experience, proposes durable changes, and applies only
approved updates to live state.

## Contract

- Observe recent sessions plus durable context
- Propose memory, skill, and fact-store changes with provenance
- Review proposals before applying
- Apply only approved changes
- Verify the updated state after writeback

## Current status

This repository is the project home and implementation workspace. The first wave
focuses on a safe MVP, clear artifact format, and testable apply/discard flow.

## Repo layout

- `brief.md` — project brief and research notes
- `research/` — overlap research and upstream references
- `specs/` — design docs and MVP contract details
- `src/hermes_dreaming/` — package source
- `tests/` — unit and integration tests

## Notes

This repo is intended to stay open-source friendly from day one: no secrets, no
hardcoded personal data, and no hidden side-effect paths.
