# System Patterns

## Architectural Principle

The core pattern is strict separation between deterministic state and creative generation. The LLM may narrate, interpret, and propose structured actions, but canonical game state must live in typed application data.

This exists because the source note identified raw LLM game-mastering as attractive but unsafe for long sessions: models can forget inventory, hallucinate hit points, ignore rules, or soften consequences unless another layer constrains them.

## Proposed App Graph

The source note originally proposed a four-node graph:

1. Orchestrator Router
2. State Manager
3. Mechanics / Oracle Node
4. Narrative Generator

The latest direction keeps the separation but changes the mechanical center from an RPG rules engine to a deterministic solo oracle.

Current graph:

1. Interaction Router
2. Oracle Engine
3. State Manager
4. Narrative Engine
5. Character Generation Layer

The first implementation expresses this as a lightweight `GameService` rather than a formal LangGraph/Pydantic AI graph. This keeps the deterministic turn loop simple while preserving the same boundaries. The target is still a fully fledged personal agentic game system; avoiding graph-framework bloat is an implementation choice, not a reduced product ambition.

The HTTP surface is intentionally thin. `src/dungeon_master/api.py` exposes one route per `GameService` operation and returns the entire `GameState` from each one. That keeps the frontend reconciler trivial (last response wins) and matches the single-writer single-user assumption. Authentication is omitted on purpose because the server binds to `127.0.0.1` and is meant to run on the user's own machine.

## Interaction Router

Responsible for classifying user input and deciding which subsystem should handle it. It should not be the source of game facts.

Today the interaction router is split across two layers:

- **Frontend slash parser** (`web/src/lib/slash.ts`): the explicit override surface. Slash commands give the player fast, precise control without round-tripping intent classification through the model. `/ask`, `/event`, `/scene`, `/chaos`, `/reset`, `/help` cover every existing oracle and admin operation. This module is unit-tested in `web/src/lib/slash.test.ts`.
- **Backend turn planner** (`src/dungeon_master/turn_router.py` + `/api/turn`): bare natural-language chat goes here. It no longer emits only a single coarse route label. The backend now asks the model for a bounded **typed action plan**: 1-3 ordered steps drawn from a fixed vocabulary (`yes_no`, `random_event`, `scene_check`, `save`, `attack`, `harm`, `recovery`, `equip`, plus non-combat prep/state-adjacent steps like `inspect_inventory`, `search_scene`, `use_item`, `drop_item`, and `narrate`). The returned `route` is still the legacy summary label for compatibility, but `GameService` now executes the ordered plan rather than switching on one enum alone. If planning is unavailable, the backend degrades to a one-step `player_action`/`narrate` plan rather than guessing with regex rules.
- **Backend `GameService`** (`src/dungeon_master/service.py`): receives a typed call (`ask_yes_no`, `random_event`, `scene_check`, `submit_action`, etc.) and runs the deterministic mechanics in the right order, never trusting the LLM with state mutation. Turn-planning failure is now explicit when the model is configured but the planner cannot produce valid structured output; the backend no longer silently degrades that case into a normal `player_action`/`narrate` turn.

Planner operations / routes that currently exist:

- Narrative-only action (ambiguous free text / `/action`)
- Yes/no oracle question (`/ask`, or bare yes/no questions via `/api/turn`)
- Random event generation (`/event`, or "something happens" prompts via `/api/turn`)
- Scene setup check (`/scene`, or obvious movement transitions via `/api/turn`)
- Cairn save / attack / harm / recovery / equip
- Non-combat prep ops inside planned turns: inspect inventory, search the current scene, use an item, drop an item
- Chaos factor adjustment (`/chaos`)
- Campaign reset (`/reset`)
- Slash help (`/help`, client-side only)

## Oracle Engine

The Oracle Engine is deterministic Python, not an LLM. It owns mechanical uncertainty and should output strict typed data.

Initial mechanics:

- Chaos Factor in the 1-9 range
- Yes/no oracle answers influenced by likelihood and chaos
- Random event generation
- Event focus and meaning prompts
- Scene setup checks for expected, altered, or interrupted scenes
- Thread and NPC references when relevant

The implementation should be inspired by Mythic GME-style principles without copying proprietary tables verbatim unless the user supplies licensed material or chooses an open table source.

The current code no longer hardcodes oracle content tables in `src/dungeon_master/oracle.py`. New campaigns ask the model to generate oracle word banks, then persist those banks in `GameState.oracle_tables`; the deterministic oracle rolls over the persisted generated tables.

## State Manager

The State Manager is not an LLM. It should be strict application logic that reads, validates, and writes canonical state.

Responsibilities:

- Chaos factor
- Active threads
- Notable NPCs
- Current scene status
- Player character notes
- World or setting notes
- Location and scene state
- Oracle history
- Checkpoints and rollback

State should be persisted to local files, most likely JSON for strict validation plus Markdown summaries for readability. Runtime validation should prevent malformed state transitions from silently becoming canon.

The current implementation persists canonical state to `data/game_state.json`, appends event log entries to `data/events.jsonl`, and writes timestamped JSON checkpoints to `data/checkpoints/`.

There is now also a separate derived-memory sidecar at `data/memory.json`. This is **not** canonical state and is intentionally kept outside `GameState`:

- it is rebuilt from committed canon rather than treated as source of truth
- it holds the app's compacted "GM notes" (`recent_turn_summaries`, `scene_summaries`, `thread_memory`, `npc_memory`, `location_memory`, `revealed_facts`, `open_loops`, `callback_candidates`)
- it is written only after committed saves, so cancel/discard semantics remain intact
- it exists to keep planner/narrator prompts bounded without replaying raw logs

The follow-up bug-fix pass tightened two important invariants around that sidecar:

- streamed turns now persist a captured **pre-narration** turn checkpoint, matching the unary regenerate contract instead of checkpointing a state that already contains the old DM response
- turn checkpoints now also persist `execution_context`, so memory rebuilds and regenerate calls can retain the exact deterministic backend-step summary that originally grounded the narration

## Mechanics Scope

The project started oracle-first: deterministic scene pacing, threads, NPCs, and consequence prompts with a fiction-only character sheet. The user has now clarified that this was **not** a final rejection of structured RPG mechanics; they want the experience grounded in rules and have chosen a **Cairn 2e-inspired dark-fantasy adaptation** as the next layer.

That means the mechanics scope is now:

- keep the existing deterministic oracle for yes/no resolution, scene checks, random events, chaos, and campaign pressure
- add a lightweight but real character rules layer: Cairn-flavored stats, HP, inventory burden/slots, armor/weapon tags, and deterministic item effects
- automatically backfill those mechanics from the already-authored character sheet and generated opening state so the user does not have to redo character creation
- keep the LLM out of canonical math, roll resolution, item modifiers, and state mutation
- in the current backend implementation, the above is realized as a separate `CairnEngine` (`src/dungeon_master/cairn.py`) that sits beside `OracleEngine`, not inside it

The preferred pattern is now:

1. Load current state.
2. Identify whether the action invokes oracle resolution, Cairn-style mechanical resolution, or both.
3. Roll internally.
4. Produce a structured outcome (oracle result, mechanical result, or both).
5. Ask the State Manager to apply validated changes, if any.

The oracle should avoid relying on model memory for procedure knowledge.

## Narrative Engine

Responsible for prose only after oracle mechanics and state have been resolved. It should receive:

- Current canonical state
- Oracle outcome
- Tone constraints
- Relevant world notes

It should not independently roll dice, change chaos factor, alter threads, modify NPCs, or mutate canonical state. Any proposed state change must be returned as structured data and validated elsewhere.

Prompt discipline now matters as much as tone. The narrator is instructed to:

- keep responses compact (usually one paragraph, at most two unless a scene transition genuinely needs more room)
- mirror the player's declared action before extending the scene
- treat item flavor, atmospheric details, and latent threats as tone rather than hardened present-tense facts unless the supplied oracle outcome / canonical state explicitly licenses them
- end on one concrete follow-up question rather than manufacturing a menu of dramatic branches

This pattern exists because "good prose" was proving insufficient on its own: the model could write stylish dark-fantasy narration while still overcommitting fiction that the oracle/state had not actually authorized.

The narrator now also receives a short **executed backend steps** summary when available. This is important after the turn-planner refactor: narration should describe what Python actually executed (e.g. checked inventory, dropped an item, then attacked) rather than reverse-engineering intent from raw player text and one coarse route label.

The narrator and turn planner now also receive a bounded **memory context** assembled from `data/memory.json`, not from the raw transcript. The key design choice is that this memory layer avoids ad-hoc lexical heuristics for meaning extraction. Instead, it leans on:

- canonical references already present in state/outcomes (`referenced_thread_id`, `referenced_npc_id`, current scene, active encounter)
- recency / active-status ordering
- compacted sidecar cards rather than replaying full `action_log` / `oracle_history`

This preserves separation of concerns: memory compaction/retrieval is an application layer, not an invitation for the narrator to treat past prose as canon.

The first memory pass rebuilt `data/memory.json` from a lossy replay of `GameState` alone. That has now been corrected: `GameService` reconstructs committed turns from canonical outcomes plus exact turn-checkpoint metadata (`player_input`, `execution_context`) before rebuilding the sidecar. This matters because explicit oracle routes (`/ask`, `/event`, `/scene`) do not always emit a player event into `action_log`, and planner-executed deterministic prep steps would otherwise vanish from derived memory.

The current implementation uses LiteLLM for model routing. The default model is OpenRouter Kimi K2.6 via `openrouter/moonshotai/kimi-k2.6`, with task-based reasoning: medium for ordinary player-action and yes/no narration, high for scene checks and random-event synthesis. Reasoning tokens are excluded from the response. When no usable API key/model configuration is present, the app returns deterministic placeholder narration so the oracle loop remains playable.

Streaming pattern:

- `src/dungeon_master/narrative.py` exposes both buffered generation (`generate_result`) and generator-based streaming (`iter_stream`) using a shared `CompletionDelta` / `NarrativeResult` contract.
- `src/dungeon_master/campaign.py` now mirrors that pattern for non-play setup flows. Character templates, quiz generation, draft generation, quizzed draft generation, and campaign world generation each have both buffered `*_result` entry points and `iter_*` generator entry points, so setup no longer needs a separate bespoke transport.
- `src/dungeon_master/service.py` lifts those into app-level result + stream methods and persists thinking where canon exists. If the stream resolves to a `GameState`, the final thinking is attached to a persisted `GameEvent`; if the stream resolves to a setup artifact (templates / quiz / draft), the final thinking is returned in the terminal API payload because there is no canonical active campaign state yet.
- `src/dungeon_master/api.py` standardizes the wire format as **NDJSON** (`Content-Type: application/x-ndjson`, one JSON object per `\n`). The lifecycle is `meta` → `thinking_delta*` → `content_delta*` → exactly one terminal `final_state` / `final_payload` / `error`. SSE was rejected because every streamed endpoint is a POST with a JSON body (EventSource is GET-only) and the frontend was already going to need a custom `fetch` + `ReadableStream` parser; NDJSON is simpler than SSE once you're parsing manually anyway.
- The frontend speaks the same NDJSON contract via `web/src/lib/streaming.ts` (`consumeStream`) + `web/src/lib/streaming-types.ts` (the discriminated `StreamEvent` union). The store branches on the typed `StreamResult` (`final` / `aborted` / `error`) without reasoning about partial-state HTTP failures. The setup-stream path now also treats server-aborted streams as explicit user-visible errors rather than silently returning `null`.
- Streaming requests now also have a **process-local cancellation contract**:
  - `src/dungeon_master/cancel.py` owns a `CancellationRegistry` keyed by `request_id`, returning cooperative `CancellationToken`s backed by `threading.Event`.
  - `src/dungeon_master/api.py` registers a token before each streamed response, emits the same `request_id` in the leading `meta` event, exposes `POST /api/requests/{request_id}/cancel`, and silently closes the NDJSON stream on `RequestCancelledError` rather than serializing cancellation as an `error`.
  - `src/dungeon_master/narrative.py`, `turn_router.py`, `campaign.py`, and `cairn.py` thread the token into LiteLLM request objects so route classification, setup generation, encounter seeding, and narrative streaming can all stop cooperatively.
  - `src/dungeon_master/service.py` treats streamed mutations as **queued until commit**: streamed player/oracle/system events are held in memory, streamed turn checkpoints are deferred until the final commit path, and `_persist_streamed_state` re-checks cancellation before writing anything. The intended semantics are discard-only: a cancelled turn leaves canonical state/event history unchanged.

## UI Pattern

The UI is a bespoke "Oracle's Ledger" Svelte 5 app served by Vite, talking to the FastAPI backend over `/api`. Streamlit was abandoned because it homogenized the aesthetic and made the dice-tumble + scene-card animations awkward.

The UI is **chat-first**: a single conversation column is the primary surface, and mechanical state lives in a peek-on-demand inspector drawer. The earlier three-column ledger (SceneCard / OracleConsole / PlayerCommand / ActionLog / sidebar drawers) was deleted because for an *AI* DM the conversation is the product; mechanics are reference. Standard solo-TTRPG dashboards put threads / NPCs / chaos in permanent eyesight, which is correct for human-GM tools but wrong here.

Current layout:

- **`StatusStrip.svelte`** (top): brand block, chaos badge (Alagard numeral), scene number, Inspect toggle.
- **`CharacterFolio.svelte`** (left rail): always-visible character sheet + condition + inventory. This is the only persistent rail because identity and carried objects directly inform every action declaration.
- **`ChatFeed.svelte`** (center, single readable column ~72ch): chronological feed of DM messages, player actions, and engine-voice system messages, derived from `state.action_log` + `state.oracle_history` + ephemeral client notes.
- **`ChatMessage.svelte` + `MechanicalReceipt.svelte`** (per-message): each oracle-driven DM message carries a collapsible receipt showing the dice number(s), oracle outcome fields, chaos-at-the-time, and summary. Default collapsed. This is the trust signal — the player can verify any roll without leaving the conversation.
- **`Composer.svelte`** (sticky bottom): textarea with rotating slash-command placeholder, Cmd/Ctrl+Enter to send, parses input via `lib/slash.ts`.
- **`Inspector.svelte`** (slide-in right drawer, default closed): compact chaos control row, collapsed threads, NPCs, notes editor, full oracle history, reset campaign button. All sections are collapsed by default to prevent the unusable nested-scroll/tall-dashboard behavior the user rejected.

Aesthetic conventions (codified in `web/src/styles/app.css`):

- Pigment-named CSS custom properties: `--ink-*`, `--paper-*`, `--gold-*`, `--rust-*`, `--green-verdigris`. Resist adding "primary" / "accent" tokens.
- Three-voice type system, never mixed on the same string:
  - `--font-display` = IM Fell English SC for chapter heads.
  - `--font-body` = Cormorant Garamond for the DM's narrative voice.
  - `--font-pixel` = Alagard (with VT323 fallback) for the engine's voice — chaos numeral, dice, oracle tags, kicker labels, system messages, all UI buttons.
- The `.pixel` class disables font smoothing so Alagard renders true-pixel.
- Two surface families: `.parchment` (warm bone, deckled edges, subtle stains) and `.iron` (oxidized cool black with a hairline gold rule). All cards must inherit one.
- Mechanical animation only: dice tumble, wax distorts, drawer slides. No springy / shadows-on-hover lift.
- A subtle SVG-noise overlay sits over the entire body via `body::before`.

Frontend state pattern:

- One global runes-based `GameStore` (`web/src/lib/store.svelte.ts`). Owns `GameState`, `isLoading`, `error`, `rollPhase`, `pendingOracle`, ephemeral `notes` (slash help / errors), and `inspectorOpen`.
- `GameStore` also owns an in-flight `AbortController` for best-effort client-side stop/cancel behavior and exposes setup methods for templates, character drafts, character finalization, campaign start, and narrative regeneration.
- The backend always returns the entire `GameState`, so the frontend never reconciles partial diffs.
- Single Composer entry point (`game.submit(rawText)`) routes explicit slash commands through the slash parser and sends bare chat to backend `/api/turn`.
- Oracle calls go through `runWithRoll`: the API responds first, then the store holds the narrative reveal until the dice have visibly tumbled and settled (~1.3s). This sells the fiction that mechanics are real and external to the model — load-bearing for project ethos.

Character state pattern:

- `GameState.character` is a structured `CharacterSheet` with the authored narrative fields (`name`, `archetype`, `epithet`, `backstory`, `drive`, `flaw`, `condition`, `inventory`) plus a nested `cairn` mechanics block.
- `GameState.campaign_status` gates the whole app shell: `character_creation` -> `ready_to_start` -> `active`.
- `CharacterGenerator` produces archetypal templates and scratch drafts before campaign generation exists.
- `CampaignGenerator` now accepts a finalized `CharacterSheet` and builds the world around it rather than inventing the player premise itself.
- `InventoryItem` now also carries a nested `cairn` item profile (slots, tags, weapon die, armor bonus, uses, equipped), allowing the backend to preserve the authored item prose while still treating gear mechanically.
- Legacy saves without `character` are accepted. `GameState` seeds a conservative sheet from `player_notes` so old campaigns remain playable and the left folio never crashes.
- One-time current-character migration pattern: if a live campaign or campaign start sees `character.cairn.source == "unset"`, `CairnEngine.ensure_character_state(..., allow_backfill=True)` asks the LLM for a structured Cairn backfill: stats, skills/abilities (textual specialties, not D&D modifiers), and a practical starting bundle. Biography mostly influences stats, condition, skills, abilities, and notes; inventory is intentionally kept less on-the-nose, with at most one or two biography-derived signature items. The migrated state is then persisted with `source == "narrative_backfill"`.
- `TurnRouter` now uses LLM-backed structured classification instead of regex routing. More complex Cairn interactions (attacks, incoming harm, recovery, equipment toggles) are exposed as explicit FastAPI operations so the frontend pass can choose deliberate controls rather than over-aggressive NLP inference.
- The newer combat pass also widened the router's responsibility boundary without overloading the rules engine: the router may classify intent into `attack`, `harm`, `recovery`, or `equip`, but `CairnEngine` still owns all canonical combat math and enemy-state mutation. Separation of concerns remains router -> service orchestration -> deterministic engine.
- Frontend rendering of Cairn state lives in a small dedicated module:
  - `web/src/lib/cairn.ts` — pure formatting helpers (defaults, render gating, burden tier, status priority, ability / stance / rest-kind labels, item tag labels, and the receipt headline switch). No inference, no mutation. Exhaustive Vitest coverage in `cairn.test.ts`.
  - `web/src/components/CairnReadout.svelte` — read-only stat / burden / statuses / skills / abilities / (optional) build-notes block. Surface-agnostic so it can sit inside the folio's iron rail and above the editor's parchment surface.
  - `CharacterFolio.svelte` hosts the readout for active play and renders per-item tag chips + equipped/primary badges.
  - `MechanicalReceipt.svelte` is exhaustive over `OracleKind` (TS will fail at build time when a new kind is added without a branch) and surfaces structured Cairn fields in the body when `outcome.cairn` is populated.
  - `Inspector.svelte` adds a collapsed "Cairn build notes" drawer that is hidden when the character is unset or has no notes.
  - `CharacterEditor.svelte` shows the read-only Cairn block above the editor only when the draft is already backfilled (`character.cairn.source !== "unset"`).
- The frontend Cairn pass is intentionally **read-only**. Mutations (`/api/cairn/attack`, `/harm`, `/recover`, `/equip`) stay backend-only until a follow-up explicit-controls pass binds them to UI affordances. Cairn slash commands are deliberately not added: `save` is already covered by the LLM-backed `/api/turn` router, and the other Cairn actions are GM-side / fiddly-inventory operations that don't read naturally as prose.

Regeneration pattern:

- Every turn writes a named pre-narration checkpoint keyed by `oracle_outcome_id` in addition to the normal timestamped state checkpoint.
- `POST /api/messages/{event_id}/regenerate` is only valid for the latest DM response.
- Regeneration restores the pre-narration checkpoint, preserves the existing deterministic oracle outcome, regenerates only the prose, and appends a `Narrative regenerated` system event as an audit trail.
- This keeps regenerate as a repair tool for malformed/incomplete LLM output rather than a stealth reroll.

## Reliability Patterns

The project should include:

- Typed schemas for all state and node outputs
- Retries for LLM/tool calls
- Checkpoints after each accepted turn
- Rollback to prior checkpoint
- Validation before persistence
- Append-only event log for reconstructing state
- Clear distinction between proposed changes and committed changes
- Cooperative cancellation tokens for long-running streamed work, with request IDs exposed at the API boundary

## Framework Direction

LangGraph was discussed as the initial agent-graph option because it supports cyclic workflows. Pydantic AI was also mentioned as attractive for strict structured outputs. The framework choice is still open and should be made based on simplicity, type safety, local control, and how much graph machinery the first version really needs.
