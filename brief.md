# Hermes Dreaming — Project Brief

## Goal
Build a safe, reviewable self-improvement engine for Hermes-style memory and
skill updates. The MVP must support writeback, but only through an explicit
apply step after a staged proposal is reviewed.

## Approved contract
- Read recent sessions and durable context
- Produce a staged dream artifact with proposed changes and provenance
- Allow explicit apply/discard
- Apply approved changes to live memory, skills, and fact-store targets
- Verify the resulting state after writeback

## Non-goals for v1
- Silent live mutation during analysis
- Hidden background writes without artifacts
- One-off environment failures becoming durable knowledge
- Repo secrets, tokens, or private operational data

## Overlap research
The upstream Hermes repo already has overlapping open work in flight. This repo
should stay clearly scoped as a standalone implementation of the contract, not
a duplicate of upstream PR text. Relevant references discovered during research:
- Hermes issue #10771 — Automatic Memory Consolidation (Auto Dream)
- Hermes issue #5533 — Dreaming reflection mode across CLI and gateway
- Hermes issue #30220 — background review misclassifies memory/skill/user stores
- Hermes PR #5641 — Dream Mode idle-time memory processing pipeline
- Hermes PR #9225 — local-first memory recall and dreaming MVP
- Hermes PR #10177 — manual sleep memory consolidation
- Hermes PR #21212 — Anthropic-inspired features including Dreaming
- Hermes PR #15426 — self-evolution plugin

## Success criteria
- Repo is buildable and testable locally
- Dream artifacts are deterministic enough to review
- The apply step is explicit and safe
- Tests prove discard/apply behavior and catch bad proposals
- No embarrassing leaked or incorrect repo content
