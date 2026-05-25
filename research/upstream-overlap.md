# Upstream overlap research

Date: 2026-05-25

## Scope checked
- Local brief: `brief.md`
- Local scaffold: `README.md`, `pyproject.toml`, `src/hermes_dreaming/cli.py`, `tests/test_smoke.py`
- Official upstream repo checked: `NousResearch/hermes-agent`

## What the local repo is trying to be
The local brief already defines the right shape: a safe, staged self-improvement engine with explicit apply/discard, deterministic artifacts, provenance, and no silent live mutation.

That means this repo should stay focused on the contract itself, not on re-creating upstream experiments or UI nouns.

## Upstream work already in flight
All of the items below were open when checked.

### 1) User-facing Dreaming / reflection mode
- Issue #5533, "feat(dreaming): introduce stable Dreaming reflection mode across CLI and gateway"
- Scope: a first-class `/dreaming` reflection command/path across CLI + gateway, with usable responses and tests.
- Status note: open issue, not just a discussion.

### 2) Automatic memory consolidation / auto-dream
- Issue #10771, "Automatic Memory Consolidation (Auto Dream)"
- Issue #25309, "Dreaming — Automatic Background Memory Consolidation"
- Issue #29431, "Plugin Proposal: Dreaming — Automatic Background Memory Consolidation"
- PR #5641, "Dream Mode — idle-time 5-stage memory processing pipeline" (open, mergeStateStatus DIRTY)
- PR #9225, "Add local-first memory recall and dreaming MVP" (open, DIRTY)
- PR #10177, "Feat/sleep memory" (open, DIRTY)
- PR #30199, "auto-prune low-value entries with metadata tagging and scoring" (open)

This cluster already covers the obvious "dream at idle, scan memory, score, dedupe, prune, promote" space.

### 3) Background self-improvement review / routing / safety
- Issue #30220, "Background Self-Improvement Review misclassifies content between memory/skill/user stores"
- Related open review-routing / notification / gating work: #16761, #18871, #15543, #30820, #30812, #9055, #30531, #30970
- Related PRs: #15508, #30971, #24392, #24846, #31609, #26547, #27422, #16006, #28727, #27510

This is the upstream review pipeline and its guardrails. It is not a new dream contract; it is the machinery around automated review.

### 4) Curator / skill lifecycle cleanup and safety
- Issues: #23794, #26655, #29912, #26326, #23398, #29017, #25839, #27997
- PRs: #23303, #23502, #24068, #26688, #30108, #23104, #21614

Curator work is already heavily active around rollback safety, archive behavior, cron references, and skill protection. That space is crowded.

## What this repo must not duplicate
1. Do not build another user-facing `/dreaming` reflection mode. That space is already occupied by #5533.
2. Do not duplicate the automatic background consolidation pipeline / plugin proposal / sleep-memory variants. That space is already occupied by #10771, #25309, #29431, #5641, #9225, #10177, and #30199.
3. Do not re-solve background review classification and routing from scratch. The upstream pain is already being worked in #30220 and the related review-routing PRs.
4. Do not turn curator into a parallel dream system. Curator should stay curator-like, skill lifecycle safety and cleanup, not the main dream engine.

## Scope adjustment recommendation
The cleanest upstream contribution target is narrower:
- a staged, copy-on-write dream artifact flow
- explicit create / diff / apply / discard semantics
- provenance attached to every proposed change
- no silent mutation during generation
- no background scheduling in v1

That gives the repo a distinct contribution: the safe artifact/apply contract itself, not another competing reflection or auto-prune implementation.

## Bottom line
There is real overlap upstream, and it is not hypothetical. The upstream repo already has open work for:
- reflection-style dreaming
- auto consolidation / sleep / background memory pruning
- background review fixes
- curator safety and cleanup

So if we build this repo for a PR, the pitch should be: "staged dream artifacts with explicit apply/discard," not "another Dreaming mode."