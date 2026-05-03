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
- **Backend turn router** (`src/dungeon_master/turn_router.py` + `/api/turn`): bare natural-language chat goes here. It conservatively routes obvious yes/no questions (including `[likely]` hints), scene transitions, and random-event prompts through deterministic mechanics before narration. Ambiguous text remains narrative-only. This makes the app playable like a human-DM chat without requiring slash commands for every roll.
- **Backend `GameService`** (`src/dungeon_master/service.py`): receives a typed call (`ask_yes_no`, `random_event`, `scene_check`, `submit_action`, etc.) and runs the deterministic mechanics in the right order, never trusting the LLM with state mutation.

Future addition: an **LLM intent classifier** layered over the deterministic `TurnRouter`; the current heuristics remain the fallback/checkpoint path.

Routes that currently exist:

- Narrative-only action (ambiguous free text / `/action`)
- Yes/no oracle question (`/ask`, or bare yes/no questions via `/api/turn`)
- Random event generation (`/event`, or "something happens" prompts via `/api/turn`)
- Scene setup check (`/scene`, or obvious movement transitions via `/api/turn`)
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

## Mechanics Scope

The first version should avoid a full RPG rules engine. The deterministic mechanics should focus on oracle resolution, scene pacing, threads, NPCs, and consequence prompts. Combat systems, tactical movement, HP math, spell rules, and RPG action economies are intentionally out of scope unless later requested.

The preferred pattern is:

1. Load current state.
2. Identify the applicable oracle procedure.
3. Roll internally.
4. Produce a structured oracle outcome.
5. Ask the State Manager to apply validated changes, if any.

The oracle should avoid relying on model memory for procedure knowledge.

## Narrative Engine

Responsible for prose only after oracle mechanics and state have been resolved. It should receive:

- Current canonical state
- Oracle outcome
- Tone constraints
- Relevant world notes

It should not independently roll dice, change chaos factor, alter threads, modify NPCs, or mutate canonical state. Any proposed state change must be returned as structured data and validated elsewhere.

The current implementation uses LiteLLM for model routing. The default model is OpenRouter Kimi K2.6 via `openrouter/moonshotai/kimi-k2.6`, with task-based reasoning: medium for ordinary player-action and yes/no narration, high for scene checks and random-event synthesis. Reasoning tokens are excluded from the response. When no usable API key/model configuration is present, the app returns deterministic placeholder narration so the oracle loop remains playable.

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

- `GameState.character` is a structured `CharacterSheet` with `name`, `archetype`, `epithet`, `backstory`, `drive`, `flaw`, `condition`, and `inventory`.
- `GameState.campaign_status` gates the whole app shell: `character_creation` -> `ready_to_start` -> `active`.
- `CharacterGenerator` produces archetypal templates and scratch drafts before campaign generation exists.
- `CampaignGenerator` now accepts a finalized `CharacterSheet` and builds the world around it rather than inventing the player premise itself.
- `InventoryItem` is intentionally light (`name`, `details`) until the project adds real item mechanics. It is enough for action declaration and player memory without pretending there is a full RPG equipment system.
- Legacy saves without `character` are accepted. `GameState` seeds a conservative sheet from `player_notes` so old campaigns remain playable and the left folio never crashes.

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

## Framework Direction

LangGraph was discussed as the initial agent-graph option because it supports cyclic workflows. Pydantic AI was also mentioned as attractive for strict structured outputs. The framework choice is still open and should be made based on simplicity, type safety, local control, and how much graph machinery the first version really needs.
