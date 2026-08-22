# Architecture panel learning quiz

This file tracks the user's preparation for a principal-engineer technical panel. Run one question at a time. Ask the user to explain first, then correct gaps, show the stronger answer, and record the result before continuing.

## Restarted sequence: 2026-08-21

- [x] Explain the product constraint and defend the central architectural thesis.
- [ ] Trace one ordinary turn through the current runtime.
- [ ] Separate semantic interpretation, deterministic authority, prose generation, and canonical commit.
- [ ] Explain continuity, persistence, checkpoints, derived memory, and recovery.
- [ ] Defend full-state client synchronization and the local Tauri sidecar.
- [ ] Identify scaling boundaries, architectural debt, and evidence-driven migrations.
- [ ] Complete adversarial principal-engineer panel drills.

### Restarted running record

| Question | Result | Gaps to revisit |
| --- | --- | --- |
| 1. Why not one giant dungeon-master model call? (2026-08-21) | Strong partial: clearly connected the solo-play product need to finite context, long-campaign hallucination/forgetting, persistent external state, orchestration, and separation of concerns. | Runtime campaign authority is canonical JSON state plus events/checkpoints, not Markdown. Describe model calls as specialized structured workers and a prose narrator rather than generic autonomous agents. State the sharp boundary: models interpret and narrate; deterministic Python resolves mechanics; only the backend commits canon. |
| 1A. Authority-boundary drill (2026-08-21) | Strong correction: distinguished context rot and lossy compaction from raw context-window size, clarified Markdown as a hypothetical rather than a claim about the runtime, and explained task-specific context for specialized model workers. | The current workflow is LLM-planned but Python-orchestrated: `TurnRouter` proposes a typed plan, while `GameService` executes and orders it. Model outputs are proposals until validated and committed. Persisted `GameState` is campaign canon; browser/Tauri state is only its replaceable mirror. |
| 1B. Final architecture thesis (2026-08-21) | Passed: correctly identified the workflow as programmatically sequenced by Python from the typed router result, retained the useful agentic-workflow label without claiming an LLM orchestrator, expanded Python authority to mechanics/validation/order/cancellation/commit, and identified persisted state as campaign canon with a replaceable client mirror. | Say that models propose typed operations and prose, not a replacement `GameState`; Python constructs and mutates the working state. Prefer `server-authoritative layered architecture with unidirectional state synchronization` over claiming classical MVC. |
| 2. Ordinary free-text turn, first restatement (2026-08-21) | Partial: correctly traced player input into the Python orchestrator, through model-backed routing, optional deterministic rolling, and then into narrative generation and possible state updates. | `TurnRouter` returns a typed ordered plan rather than a binary roll-or-mundane verdict. Narrate-only turns can still create durable continuity after prose. Narration remains provisional until post-prose reconciliation, persistence, and terminal `final_state`. A full returned snapshot does not mean every state field changed. |

## Archived pre-restart sequence

## Phase 1: Current mental model

- [x] Trace one natural-language turn from the composer to durable storage.
- [x] Separate deterministic Python decisions from structured LLM decisions and prose generation.
- [ ] Explain why the client replaces the complete `GameState` instead of applying local patches.

## Phase 2: Architecture and boundaries

- [ ] Compare browser development startup with the Tauri desktop startup and late-bound API base.
- [x] Explain the typed `TurnPlan` boundary and why the LLM does not directly mutate game state.
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
| 6. Runtime reviewer defense and deletion case (2026-08-20) | Strong: defended the current guard because semantic quality is otherwise unmeasured, identified correlated same-model judging, and proposed collapsing the work into one stricter planning contract. | Say `rubric`, not `Rubik`; same-model review can still catch independent-sampling errors, but deletion needs measured planner precision rather than a stricter prompt alone. |
| 7. Full-state replacement rationale (2026-08-20) | Not yet assessed: the first answer correctly identified transfer, parsing, memory, and weaker-device costs, then the user correctly refused a panel-style defense built on unexplained phrases rather than repo-specific background. | Teach the exact terminal `final_state` assignment, keyed Svelte rendering, single-writer local-sidecar constraint, coupled-state consistency benefit, measured change thresholds, and revisioned-delta migration before asking for a defense. |

## Pause

- 2026-08-20: The user paused the quiz because the repeated architecture-map failures were aggravating. Do not resume, grade, or ask another architecture question until the user explicitly asks to continue.
- 2026-08-21: The restarted quiz is paused after Question 2's first restatement. On resumption, split the turn trace into one boundary per prompt; do not ask for owner, payload, and authority classification across the entire pipeline at once.
- 2026-08-21: The user explicitly resumed the quiz after recording H-06. Continue Question 2 one seam at a time, beginning with `Input -> Plan`.
