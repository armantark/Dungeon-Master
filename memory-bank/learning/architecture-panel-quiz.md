# Architecture panel learning quiz

This file tracks the user's preparation for a principal-engineer technical panel. Run one question at a time. Ask the user to explain first, then correct gaps, show the stronger answer, and record the result before continuing.

## Restarted sequence: 2026-08-21

- [x] Explain the product constraint and defend the central architectural thesis.
- [x] Trace one ordinary turn through the current runtime.
- [x] Separate semantic interpretation, deterministic authority, prose generation, and canonical commit.
- [ ] Explain continuity, persistence, checkpoints, derived memory, and recovery.
- [ ] Defend full-state client synchronization and the local Tauri sidecar.
- [ ] Identify scaling boundaries, architectural debt, and evidence-driven migrations.
- [ ] Complete adversarial principal-engineer panel drills.

### Required hypothetical scaling drills

- [ ] Defend staying on per-save JSON, then identify measured triggers for
  SQLite or PostgreSQL and the transaction/query/concurrency gains each would
  buy relative to its operational cost.
- [ ] Defend the current structured memory retriever, then identify recall
  evidence that would justify vector or hybrid retrieval without making search
  results canonical.
- [ ] Identify thresholds for replacing full-state client snapshots with
  revisioned deltas, and for moving in-process model work onto durable queues or
  workers.
- [ ] Separate improvements required for one local solo campaign from those
  required for multi-user, cloud-hosted, or very long-running campaigns.
- [ ] Propose migrations with baselines, success metrics, rollback plans, and
  the smallest reversible intermediate step.

### Restarted running record

| Question | Result | Gaps to revisit |
| --- | --- | --- |
| 1. Why not one giant dungeon-master model call? (2026-08-21) | Strong partial: clearly connected the solo-play product need to finite context, long-campaign hallucination/forgetting, persistent external state, orchestration, and separation of concerns. | Runtime campaign authority is canonical JSON state plus events/checkpoints, not Markdown. Describe model calls as specialized structured workers and a prose narrator rather than generic autonomous agents. State the sharp boundary: models interpret and narrate; deterministic Python resolves mechanics; only the backend commits canon. |
| 1A. Authority-boundary drill (2026-08-21) | Strong correction: distinguished context rot and lossy compaction from raw context-window size, clarified Markdown as a hypothetical rather than a claim about the runtime, and explained task-specific context for specialized model workers. | The current workflow is LLM-planned but Python-orchestrated: `TurnRouter` proposes a typed plan, while `GameService` executes and orders it. Model outputs are proposals until validated and committed. Persisted `GameState` is campaign canon; browser/Tauri state is only its replaceable mirror. |
| 1B. Final architecture thesis (2026-08-21) | Passed: correctly identified the workflow as programmatically sequenced by Python from the typed router result, retained the useful agentic-workflow label without claiming an LLM orchestrator, expanded Python authority to mechanics/validation/order/cancellation/commit, and identified persisted state as campaign canon with a replaceable client mirror. | Say that models propose typed operations and prose, not a replacement `GameState`; Python constructs and mutates the working state. Prefer `server-authoritative layered architecture with unidirectional state synchronization` over claiming classical MVC. |
| 2. Ordinary free-text turn, first restatement (2026-08-21) | Partial: correctly traced player input into the Python orchestrator, through model-backed routing, optional deterministic rolling, and then into narrative generation and possible state updates. | `TurnRouter` returns a typed ordered plan rather than a binary roll-or-mundane verdict. Narrate-only turns can still create durable continuity after prose. Narration remains provisional until post-prose reconciliation, persistence, and terminal `final_state`. A full returned snapshot does not mean every state field changed. |
| 2A. Input to plan, mundane action (2026-08-21) | Passed: correctly classified thanking Kaelen and sitting beside the fire as a mundane action that directs the character without requiring mechanics. | State the concrete plan shape when challenged: legacy route `player_action`, one `narrate` op, and no authority at this seam to roll, narrate the result, or mutate state. |
| 2B. Plan to deterministic resolution (2026-08-21) | Passed: correctly identified that Python rolls the die and checks it against the selected stat before narration. | Name the structured handoff: Python produces an `OracleOutcome` carrying the roll, target ability score, success verdict, reason, and Cairn resolution; narration receives resolved facts rather than permission to reroll. |
| 2C. Resolution to narration (2026-08-21) | Passed: correctly read roll-under Cairn semantics (`7 < 12` passes) and explained that the narrator must incorporate the resolved facts plus relevant threads and NPC context into prose. | The narrator may choose how the success manifests, but cannot reverse the verdict, change the roll/score, or mutate continuity directly. Post-narration workers propose durable thread/NPC changes for Python to validate and apply. |
| 2D. Narration to continuity reconciliation (2026-08-21) | Passed: correctly identified that durable prose must run through the thread and NPC updaters rather than writing directly to `GameState`. | The continuity classifier selects `threads`, `npcs`, `both`, or `none`; selected model-backed updaters return structured operations, and Python validates/applies those proposals to working state. |
| 2E. Reconciliation to commit, first answer (2026-08-21) | Partial: correctly inferred that an updated in-memory working object is not yet canonical and that persistence must succeed first. | Learn the concrete sequence: write the turn checkpoint, append queued events, atomically replace canonical `game_state.json` and write a general checkpoint, rebuild/write derived `memory.json`, then emit terminal `final_state`. The individual file replacements are atomic; the multi-file sequence is not one database transaction. |
| 2E-1. Canonical versus derived persistence (2026-08-21) | Passed: correctly identified `game_state.json` as campaign canon and `memory.json` as disposable, rebuildable derived context. | Remember that event history and checkpoints also support reconstruction/recovery even though `game_state.json` is the authoritative current snapshot. |
| 2F. Commit to client mirror (2026-08-21) | Passed: correctly explained that the frontend stores the returned snapshot in memory and Svelte runes update affected elements without rebuilding the complete DOM. | The exact operation is `this.state = event.state` on a `$state` field; keyed message rendering lets Svelte retain existing DOM nodes by stable message id. Question 2 is mastered across all six seams. |
| 3A. Semantic interpretation versus mechanical authority (2026-08-21) | Partial: correctly inferred that the coercion scenario calls for a mental-stat save, while noting that the exact Cairn stat felt like mechanics trivia rather than architecture. | Cairn has no INT stat; concrete coercion/exposure maps to `WIL`. More importantly, `TurnRouter` proposes the typed `save`/ability based on meaning, while `CairnEngine` performs the roll and resolves it. Use `proposes`, not `runs`, for router ownership. |
| 3A-1. Planner versus mechanics restatement (2026-08-21) | Passed: reduced the seam to action versus roll. | Panel phrasing: `TurnRouter` proposes the typed action based on meaning; `CairnEngine` determines the mechanical outcome through canonical rules and randomness. Together with Questions 2B-2E, this completes the interpretation/mechanics/prose/commit objective. |
| 4A. Derived-memory recovery (2026-08-21) | Passed: correctly chose rebuilding an absent or invalid `memory.json` instead of stopping play or trusting stale derived data. | `memory.json` is best described as a rebuildable derived read model or materialized view for bounded LLM context, not campaign canon. The current rebuild uses `GameState.oracle_history` and `GameState.action_log`, enriched by exact player input and execution context from turn checkpoints. |
| 4B. Why bound model context (2026-08-21) | Passed: identified both direct inference cost and context rot from sending the complete campaign to every worker. | Add latency, irrelevant-context interference, and separation of concerns. The existing memory layer is already a narrow structured retrieval-augmented pattern without embeddings; vector RAG is not justified until campaign scale or recall measurements show a retrieval problem. Prompt caching can reduce repeated-prefix cost but cannot reduce context rot, and this app currently neither configures explicit cache controls nor records cache-read telemetry. |
| 4C. Cancellation transaction boundary (2026-08-21) | Passed: correctly identified cancellation as aborting the complete in-flight turn and raised the unresolved roll-finality question. | Current behavior is discard-only: partial prose, state mutations, queued events, checkpoints, memory updates, and resolved rolls remain uncommitted. Resubmission rerolls, so save scumming is possible; the frontend also clears rather than restores the submitted Composer text. Preserving a revealed roll while editing the action is a separate transaction-design problem because the edited action may require different mechanics. |
| 4D. Turn-checkpoint purpose, first answer (2026-08-21) | Not yet: attributed accepting the next player response or command to the turn checkpoint. | Accepting the next turn comes from loading canonical current `GameState`. The turn checkpoint instead captures the mechanics-resolved, pre-narration boundary plus the original input and execution context. Regeneration restores it so prose and downstream reconciliation can be replaced without rerunning the original plan or dice. |
| 4D-1. Checkpoint regeneration restatement (2026-08-21) | Partial: correctly recognized checkpoints as a rollback boundary, but described regeneration as replacing state while preserving prior messages. | More precise: restore the mechanics-resolved pre-narration state; replace the narrative and narration-dependent continuity; keep the original player input, typed execution, and resolved outcome/roll fixed. This is latest-response repair, not general campaign rollback. |
| 4D-2. Checkpoint regeneration final restatement (2026-08-21) | Passed: stated that narration is rewritten while the original input and mechanical outcome are not rerolled. | Panel phrasing: restore the mechanics-resolved pre-narration checkpoint, regenerate prose, rerun narration-dependent reconciliation, and recommit without replanning or rerolling the turn. |
| 4E. Multi-file crash consistency (2026-08-21) | Strong partial: correctly identified that a crash between event/checkpoint writes and canonical-state replacement can leave the files disagreeing, and proposed collapsing persistence into one write boundary. | Use the term `atomic transaction`, not `one record`: state, events, and checkpoints can remain separate logical records while committing all-or-nothing. SQLite is the proportionate local migration; PostgreSQL is justified only by remote multi-process concurrency or operational requirements. A transaction journal plus commit marker is the file-based alternative. |
| 4E-1. Whether to migrate now (2026-08-21) | Defensible with one panel-language correction: chose migration because the known multi-file crash window is a present correctness issue and future asynchronous multiplayer increases the value of transactional persistence. | Do not argue that LLMs trivialize a data migration. They reduce coding effort but not data inventory, compatibility, cutover, rollback, crash testing, schema evolution, or packaged-runtime risk. Keep two decisions separate: embedded SQLite can fix local atomicity now; hosted multiplayer may later justify PostgreSQL plus revisions, idempotency, authentication, and conflict policy. |

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
