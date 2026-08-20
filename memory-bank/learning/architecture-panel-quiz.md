# Architecture panel learning quiz

This file tracks the user's preparation for a principal-engineer technical panel. Run one question at a time. Ask the user to explain first, then correct gaps, show the stronger answer, and record the result before continuing.

## Phase 1: Current mental model

- [ ] Trace one natural-language turn from the composer to durable storage.
- [ ] Separate deterministic Python decisions from structured LLM decisions and prose generation.
- [ ] Explain why the client replaces the complete `GameState` instead of applying local patches.

## Phase 2: Architecture and boundaries

- [ ] Compare browser development startup with the Tauri desktop startup and late-bound API base.
- [ ] Explain the typed `TurnPlan` boundary and why the LLM does not directly mutate game state.
- [ ] Explain Oracle versus Cairn responsibilities and how their results become narration context.
- [ ] Explain why post-narration thread and NPC continuity work runs after committed prose.
- [ ] Explain canonical state, append-only events, checkpoints, and derived `MemoryState`.
- [ ] Explain save isolation, active-save rebinding, in-flight guards, and stream reattachment.

## Phase 3: Tradeoffs and failure modes

- [ ] Defend FastAPI plus Svelte plus a bundled Python sidecar inside Tauri.
- [ ] Defend full-state synchronization and identify where it stops scaling.
- [ ] Identify the dormant `mechanics_ready` and `oracle_outcome` client contract and propose a clean resolution.
- [ ] Explain model-provider configuration, credential boundaries, retries, and deterministic fallbacks.
- [ ] Trace the desktop build and release pipeline and name its highest-risk seams.

## Phase 4: Principal-engineer panel

- [ ] Give a two-minute architecture overview that starts with product constraints, not technologies.
- [ ] Answer a challenge to replace deterministic mechanics with one large agent prompt.
- [ ] Answer a challenge to replace the local sidecar with a hosted backend.
- [ ] Describe the most important architectural debt without undermining the overall design.
- [ ] Propose the next scaling boundary and the evidence that would justify crossing it.

## Running record

| Question | Result | Gaps to revisit |
| --- | --- | --- |
| 1. Natural-language turn mental model (2026-08-19) | Partial: correctly identified classification, deterministic mechanics, grounded narration, and post-narration continuity updates. | Correct the ordering; separate NPC/thread context from post-prose updates; explain that rolls are conditional; include atomic persistence and wholesale client-state replacement. |
