# Upstream overlap research

## What is already in flight in `NousResearch/hermes-agent`

The upstream repo already has multiple open items in the exact neighborhood of this project:

- **#10771** — *Feature Request: Automatic Memory Consolidation (Auto Dream)*
- **#5533** — *feat(dreaming): introduce stable Dreaming reflection mode across CLI and gateway*
- **#30220** — *Background Self-Improvement Review misclassifies content between memory/skill/user stores*
- **#18369** — *Nudge counters reset on /new — self-improvement never triggers for short-session users*
- **#19324** — *policy to control whether write operations need approval before being learned during self-improvement*
- **#22112** — *Add self-improvement guardrail for repeated equivalent tool timeouts*
- **#5641** — *feat: Dream Mode — idle-time 5-stage memory processing pipeline* (open PR)
- **#9225** — *Add local-first memory recall and dreaming MVP* (open PR)
- **#10177** — *Feat/sleep memory* (open PR)
- **#21212** — *4 Anthropic-inspired agent features (Dreaming, Outcomes, Orchestration, Webhooks)* (open PR)
- **#15426** — *feat: add self-evolution plugin — agent self-optimization system* (open PR)

## What this means for this repo

This repository should **not** try to copy upstream PR text or reimplement the same feature names as if they were new discoveries. The safe path is:

- implement the **staged apply/discard contract** explicitly
- keep the repo standalone and open-source friendly
- avoid claiming novelty for the basic Dreaming idea
- focus on the artifact lifecycle, safety gates, and writeback verification
- make the implementation easy to review and easy to upstream later if desired

## Scope adjustment

Based on the overlap, the MVP should be framed as:

> a standalone staged self-improvement engine that produces reviewable dream artifacts and applies approved memory/skill/fact updates safely.

That keeps the repo aligned with the approved contract without pretending the idea is brand-new.

## Guardrails for the rest of the build

- Do not leak private or user-specific content into docs or tests.
- Do not over-claim features that are still only proposals upstream.
- Do not duplicate upstream issue wording verbatim in README or package metadata.
- Keep the implementation small, testable, and explicit about writeback behavior.
