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
| 2. Runtime stage ordering and location (2026-08-19) | Correct: all six stages were ordered exactly, and the first five were correctly identified as backend with only client replacement on the frontend. | Distinguish proposal, working-state mutation, durable persistence, and frontend mirroring without treating those implementation effects as inherently exclusive. |
| 3. Mechanics-before-narration rationale (2026-08-19) | Strong partial: identified dice as the authority on what happens and independently recalled the chicken-or-egg tension between simulation and ad hoc prose. | Distinguish model-based semantic planning from deterministic Python simulation; explain pre-prose constraints versus post-prose canonization. |
| 4. Failure-consequence design (2026-08-19) | Strong insight: identified the retroactive-contrivance failure mode where a bad roll forces the narrator to invent an unearned adverse event. | Apply the tabletop principle of establishing meaningful uncertainty and bounded stakes before rolling, then test it against a concrete scene. |
| 5. Semantic-stakes verification tradeoff (2026-08-19) | Correct critique: recognized that arbitrary-language stakes cannot be proved by deterministic validation and that adding another model judge increases orchestration complexity. | Identify the existing save-review call, then distinguish a runtime guard from an offline evaluation that could justify deleting it. |
