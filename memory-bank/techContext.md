# Tech Context

## Current Repository State

The workspace now contains a Python FastAPI backend, a Svelte 5 + Vite + TypeScript frontend, the Memory Bank, and an initialized git repository.

The workspace path is:

`/Users/ArmanTarkhanian1/Desktop/dungeon-master`

The repository was initialized locally on `main` and currently has an initial commit.

## Stack

Backend (Python):

- FastAPI exposes the game over HTTP/JSON.
- Uvicorn serves it; the `dungeon-master` console script (defined in `pyproject.toml`) wraps it.
- Pydantic models for state, events, and request/response schemas.
- Deterministic oracle engine in pure Python.
- LiteLLM for provider-agnostic LLM calls (default OpenRouter Kimi K2.6).
- `python-dotenv` for local config.
- Local `data/game_state.json`, `data/events.jsonl`, and `data/checkpoints/` for canonical state.
- Local `data/memory.json` for derived compacted GM-note memory used to bound planner/narrator prompt context.

Frontend (Svelte 5 + Vite + TypeScript, plain — no SvelteKit):

- Lives in `web/`. Svelte 5 with the runes API (`$state`, `$derived`, `$effect`, `$props`).
- Vanilla CSS with custom properties; no Tailwind. The bespoke "Oracle's Ledger" aesthetic depends on per-component SVG textures, deckled paper masks, gold rules, and 3D dice transforms that Tailwind's utility model would homogenize.
- Vite proxies `/api` -> `http://127.0.0.1:8000` by default.
- Dev-only frontend override: `web/vite.config.ts` now honors `VITE_API_PROXY_TARGET` before falling back to `http://127.0.0.1:8000`, so a second frontend dev server can target an isolated fixture backend without editing checked-in config.
- Runtime types are hand-mirrored in `web/src/lib/types.ts` to match `src/dungeon_master/models.py`.

Implemented components:

Backend:

- `src/dungeon_master/api.py`: FastAPI app + routes for state, oracle, action, reset, setup, and streaming. F-06 adds `POST /api/campaign/end`, which accepts an explicit `CampaignEndReason` plus optional summary and returns the full terminal `GameState`. F-10 backend adds `POST /api/explain` and `/api/explain/stream`, which return non-canonical answer payloads instead of mutating state. F-12 backend adds `GET /api/library/bootstrap`, `POST /api/library/saves`, and `POST /api/library/select` for the save library. F-16/B-02 backend adds `POST /api/state/directives`, a durable OOC steering endpoint separate from `/api/state/notes`. The newer scene-memory/oracle split pass adds `POST /api/oracle/yes-no/preview`, a read-only yes/no oracle endpoint that returns an `OracleOutcome` without mutating `GameState`; the existing `POST /api/oracle/yes-no` route remains the committed gameplay path for the current frontend. App startup can now boot through a `SaveLibrary` instead of binding directly to one flat state path, and `get_service(...)` returns a `409 No active save selected.` conflict when the library exists but no slot is active.
- `src/dungeon_master/cli.py`: `dungeon-master` console script that runs uvicorn.
- `src/dungeon_master/observability.py`: small backend trace helper for INFO-level `llm.call`, `turn.router`, and `continuity.classifier` lines. It centralizes token/duration formatting and reads `DM_LOG_LEVEL` for runtime visibility.
- `src/dungeon_master/stream_session.py`: detached stream-session layer used by FastAPI streaming routes. It buffers already-serialized NDJSON, supports replay + live-tail subscribers, tracks per-request save scope, and lets disconnects detach the subscriber without cancelling the producer thread.
- `src/dungeon_master/campaign.py`: model-driven campaign bootstrap and oracle table generation.
- `src/dungeon_master/models.py`: Pydantic state and event schemas, including `CampaignStatus`, `CampaignEndReason`, `CharacterSheet`, `InventoryItem`, `NPCStatus`, `EncounterInitiator`, and `OracleOutcome`'s continuity linkage (`referenced_thread_id` / `referenced_thread_ids` for threads, `referenced_npc_id` / `referenced_npc_ids` for recurring cast updates). `EncounterState.initiator` + `CairnResolution.combat_initiator` are the minimal F-05 metadata for enemy-opened fights. F-06 extends `GameState` itself with terminal lifecycle metadata (`campaign_end_reason`, `campaign_ended_at`, `campaign_end_summary`) rather than introducing a separate archive/save wrapper. F-16/B-02 extends `GameState` again with `npc_roster_version`, visible `npcs`, backend-only `hidden_npcs`, and a separate `CampaignDirectives` model (`world_guidance`, `play_guidance`). H-01 further extends `NPC` with `player_label` plus `player_label_kind` (`proper_name | descriptor`) so the backend can keep a canonical true name while rendering a safe player-facing label. The old `setting_notes` / `player_notes` fields remain intact for campaign/backstory canon; directives are a new OOC steering layer, not a rename-in-place.
- `src/dungeon_master/oracle.py`: deterministic oracle engine.
- `src/dungeon_master/cairn.py`: Cairn 2e-inspired rules engine. Deterministic math stays here (saves, attacks, harm/critical damage/scars, recovery, equipment toggles, derived armor/burden recomputation), while one-time character backfill is now LLM-backed and returns a structured mechanics record plus a practical starting bundle. F-05 adds `resolve_enemy_opener(...)`, widens encounter seeding from player-led escalation to a general combat trigger with explicit initiator, and keeps generic `suffer_harm()` separate so non-combat damage does not accidentally start encounters.
- `src/dungeon_master/config/`: typed runtime/model config package. `app.py` defines `AppConfig`, `LLMConfig`, `TaskProfile`, and `LLMProfiles`; `README.md` explains the env surface and why narrator-facing knobs stay separate from low-temperature structured-call profiles.
- `src/dungeon_master/npc_updater.py`: focused backend-only structured updater for recurring NPC canon. It consumes current scene/player input/resolved outcome/execution context/current NPCs plus bounded memory context, validates a bounded `create | update | retire` op batch, and applies canonical NPC mutations in Python before checkpointing/narration. F-16 widens each op with `player_visible: bool`, lets the updater reason over the full canonical cast (visible + hidden), and adds a one-time legacy roster reseed helper for pre-split saves. H-01 widens the prompt/output contract again with `player_label` + `player_label_kind`, allowing the model to keep a backend canonical name while authoring a safe descriptor-visible roster label.
- `src/dungeon_master/thread_updater.py`: focused backend-only structured updater for campaign threads. It consumes current scene/player input/resolved outcome/execution context/current threads plus bounded memory context, validates a bounded `create | update | resolve` op batch, and applies canonical thread mutations in Python before checkpointing/narration.
- `src/dungeon_master/continuity_classifier.py`: tiny backend-only continuity scope classifier. It makes one cheap LiteLLM call and expects a single token (`none | threads | npcs | both`) rather than a full structured update payload. The purpose is to percolate continuity work more intelligently without introducing a deterministic lexical gate; if the classifier is unavailable or malformed, runtime falls back to `both`.
- `src/dungeon_master/state_store.py`: JSON state, JSONL event log, timestamped checkpoints, and named pre-narration turn checkpoints for regeneration.
- `src/dungeon_master/save_library.py`: minimal local save-library layer for F-12. Owns `data/library.json`, one-time migration from the legacy flat `data/` layout into per-save directories under `data/saves/<save_id>/`, slot creation/selection, and server-side derivation of character-facing save summaries (`character_name`, `character_epithet`, identifying line, hover summary).
- `src/dungeon_master/explainer.py`: dedicated OOC explainer client/prompt. It reuses the LiteLLM completion primitives from `narrative.py` but keeps the prompt contract separate, grounding answers in the app's actual implemented mechanics plus current state / latest outcome / bounded memory context.
- `src/dungeon_master/narrative.py`: LiteLLM narrative client with retries, Kimi/OpenRouter defaults, fallback narration, and streaming helpers that emit `CompletionDelta` chunks carrying both prose and reasoning.
- `src/dungeon_master/service.py`: application service coordinating oracle, state, narration, and campaign generation. It now also exposes result-bearing and streaming setup methods so setup and active play share one backend transport pattern. F-05 extends the Cairn protocol with `resolve_enemy_opener(...)` and teaches `_execute_turn_plan(...)` to dispatch the planner's internal `enemy_opener` op there instead of to plain `suffer_harm()`. F-06 adds one explicit `end_campaign(...)` helper for retirement/victory, automatic death finalization inside `_commit_oracle_turn(...)` / `_stream_oracle_turn(...)`, `load_state()` synchronization of legacy `active + dead` saves into canonical `ended + death`, and a reason-aware `_ensure_active(...)` guard that blocks further mutating play once the run is terminal. F-10 backend adds `explain(...)` / `stream_explain(...)` plus a read-only state-loading helper so OOC rules answers can use the same state/memory seams without writing `game_state.json`, `events.jsonl`, checkpoints, or `memory.json`. F-12 adds `bind_store(...)` and `new_setup_state()` so the FastAPI app can keep one live gameplay service and rebind it to the selected save slot without threading `save_id` through every gameplay route. F-16/B-02 adds `update_directives(...)`, a one-time load-time NPC roster repair for legacy saves, and a deterministic post-narration reveal step that moves a hidden NPC into the visible roster when committed prose explicitly names them. H-01/H-02 extend that seam further: visible descriptor NPCs are promoted to proper-name labels when narration grants the name, and persisted `OracleOutcome.referenced_npc_ids` are filtered to the visible roster so receipt/navigation surfaces can treat them as player-safe links. The latest backend optimization adds a continuity-scope decision just before the expensive thread/NPC updater calls: `_apply_continuity_updates_for_turn(...)` asks `ContinuityClassifier` whether the turn needs `none`, `threads`, `npcs`, or `both`, runs only that subset, then still normalizes outcome linkage fields so downstream receipt/highlight behavior stays stable. The newer scene-memory/oracle split pass adds `preview_oracle(...)`, scene snapshot stamping on every committed `OracleOutcome`, scene-number advancement only on material scene-frame changes, and prompt assembly that feeds the full current-scene transcript to the planner/narrator while keeping older scenes compacted in `memory.json`. The new one-time maintenance path is `backfill_current_save(apply: bool, ...) -> SaveBackfillReport`, which explicitly audits/applies those same repair steps for a chosen save and forces a `memory.json` rebuild without reseeding the campaign.
- FastAPI streamed routes no longer let the HTTP response own model progress. `src/dungeon_master/api.py` now registers each streamed request in `SessionRegistry`, launches the real generator on a shared `ThreadPoolExecutor`, and publishes NDJSON into the session buffer. `GET /api/requests/{request_id}/stream` reattaches to that buffer, replays prior deltas, and rejects mismatched save scopes with `409`.
- `src/dungeon_master/backfill_cli.py`: backend maintenance CLI. Resolves either the active save slot or an explicit `--save-id`, runs `GameService.backfill_current_save(...)`, defaults to dry-run, and supports `--apply` plus `--json` report output.
- `src/dungeon_master/fixture_cli.py`: dev-only fixture seeding CLI. `dungeon-master-fixtures` writes an isolated save-library root with canned saves for browser/manual smoke (`Fixture Bellringer` for continuity-link + descriptor-roster coverage, `Fixture Archive` for ended-shelf coverage). The default root lives under `tempfile.gettempdir()`, `--force` is required to replace an existing fixture root, and the fixture states explicitly set `npc_roster_version=2` so load-time legacy-roster repair does not silently rewrite them.
- `src/dungeon_master/turn_router.py`: LiteLLM-backed natural-language planner for `/api/turn`. The legacy summary route still stays in the older public set (`player_action`, `yes_no`, `random_event`, `scene_check`, `save`, `attack`, `harm`, `recovery`, `equip`, `retreat`), but the op vocabulary is richer: F-05 adds an internal-only `enemy_opener` op so prose ambushes can seed combat while the public route/outcome remains `harm`. It still falls back to `player_action` if the model is unavailable rather than using regex inference.
- `src/dungeon_master/settings.py`: thin compatibility wrapper around `AppConfig.from_env().state_path`.

Frontend:

- `web/src/main.ts`, `web/src/App.svelte`: entry + setup-aware layout (CharacterSetup before campaign start; StatusStrip → CharacterFolio + ChatFeed → Composer → Inspector once active).
- `web/src/lib/api.ts`: thin fetch wrapper, now also exposing character template/draft/finalize/start and message-regenerate endpoints. The streaming Phase 2 frontend pass adds `reattachStream(requestId, handlers, signal?)` against the new backend `GET /api/requests/{id}/stream` route; it shares the same NDJSON transport via `consumeStream` and just toggles its new `method: "GET" | "POST"` option. The newer `/ask` split adds `previewYesNo(question, likelihood, signal?)` against `POST /api/oracle/yes-no/preview`, while the legacy `askYesNo(...)` call remains available for the still-canonical committed oracle route.
- `web/src/lib/stream-resume.ts` + `stream-resume.test.ts`: tiny localStorage helper for the "reload mid-stream" promise. Owns a per-save descriptor (`request_id`, `route`, `started_at`, `save_id`) under the key `dm.stream-resume.<save_id>`, with a 10-minute TTL, defensive shape validation, eviction of stale or corrupt rows, and a no-op fallback when storage is unavailable. The store writes the descriptor on the `meta` event, clears it on terminal events / cancel / fallback, and `bootstrap()` reads it to fire `#tryResumeStream()` after `getState` succeeds. The resumed stream sets `streaming.resuming = true` so `ChatMessage.svelte` can swap its meta tag from `"streaming…"` to `"resuming…"` with a verdigris accent.
- `web/src/lib/store.svelte.ts`: single runes-based `GameStore` owning `state`, `isLoading`, `error`, `rollPhase`, `pendingOracle`, `cancelLabel`, ephemeral `notes`, and `inspectorOpen`. Exposes setup actions, `submit(rawText)`, `regenerateMessage(eventId)`, and `cancelCurrentRequest()`. `/ask` now routes through the read-only preview endpoint and lands a session-only OOC note (`oracle_preview`) instead of mutating `GameState` or triggering the roll animation.
- `web/src/lib/slash.ts` + `slash.test.ts`: pure slash-command parser (`/ask`, `/event`, `/scene`, `/chaos`, `/reset`, `/help`, `/retreat` with `/flee`+`/disengage` aliases, and the four acquisition verbs `/acquire`, `/loot`, `/take`, `/buy` with `/gain` and `/purchase` aliases) with Vitest coverage. The same `SLASH_COMMANDS` descriptor list backs the suggestion menu in `Composer.svelte`. `/ask` is now explicitly described in the help/suggestion copy as a **read-only oracle preview** rather than a committed gameplay turn.
- `web/src/lib/character.ts` + `character.test.ts`: pure setup helpers (`deriveSetupMode`, `blankCharacterDraft`) plus latest-message regeneration eligibility helper (`message-actions.ts`).
- `web/src/lib/quiz.ts` + `quiz.test.ts`: assist-mode interview helpers (answer state, validation, payload builder).
- `web/src/lib/cairn.ts` + `cairn.test.ts`: pure Cairn formatting helpers (defaults mirroring `models.py`, render gating, burden tier, priority-ordered status badges, ability/stance/rest-kind labels, item tag labels, and the exhaustive `cairnHeadline` switch over `save | attack | harm | recovery | retreat`). F-05 added `formatCombatInitiator(...)`, `isAmbushOpener(outcome)`, and a harm-headline rewrite that prepends `"Ambush · "` only when the resolution is structurally an enemy opener (`combat_started === true && combat_initiator === "enemy"`).
- `web/src/lib/threads.ts` + `threads.test.ts`: pure helpers for the dynamic-thread inspector surface. `recentlyTouchedThreadIds(state, lookback?)` derives the just-touched set from the latest oracle outcome's plural `referenced_thread_ids` (with a fallback to the legacy singular `referenced_thread_id` so older state blobs still highlight). `sortThreadsForDisplay(threads, touched)` returns a stable display order — active before resolved, recently-touched first within each status group, canonical insertion order preserved within ties, input array not mutated. `ThreadsPanel.svelte` consumes both; `Inspector.svelte` owns the derivation.
- `web/src/lib/npcs.ts` + `npcs.test.ts`: the structural dual of `threads.ts` for the dynamic-NPC inspector surface. `recentlyTouchedNpcIds(state, lookback?)` reads the latest oracle outcome's plural `referenced_npc_ids` (with a fallback to the legacy singular `referenced_npc_id`). `sortNpcsForDisplay(npcs, touched)` returns a stable order — active before retired, recently-touched first within each status group, canonical insertion order preserved within ties, input array not mutated. H-01 extends the module with `npcDisplayLabel()` / `npcKnownByDescriptor()` so every player-facing render path prefers the safe `player_label`, and H-02 adds `referencedNpcsForOutcome(...)` so receipt pills resolve only against the visible roster the frontend already has in hand. `NPCsPanel.svelte` consumes the label helpers and the touched/focus signals; `Inspector.svelte` owns the derivation. Both helper modules are deliberately pure (no Svelte runes, no DOM) so they unit-test without a component harness.
- `web/src/lib/types.ts`: TS mirrors of `GameState`, `OracleOutcome`, plus the new Cairn enums and nested mechanics state (`CairnAbility`, `AttackStance`, `CairnRestKind`, `CairnItemTag`, `CairnMechanicsSource`, `CairnItemState`, `CairnCharacterState`, `CairnResolution`). The `OracleKind` union now includes `save | attack | harm | recovery | retreat` so the receipt switch is exhaustive at compile time. `OracleOutcome.referenced_thread_ids: string[]` mirrors the F-03 plural thread linkage; the legacy singular `referenced_thread_id` is retained for older state blobs. F-05 adds the `EncounterInitiator` union (`"player" | "enemy"`) and extends `CairnResolution` with optional combat-context fields (`combat_initiator`, `combat_started`, `combat_active`, `combat_round`, `player_acted`, `enemy_damage`, `enemy_damage_source`); they are optional so most non-combat outcomes can omit them and existing test factories don't have to spell them out. H-01 further extends `NPC` on the frontend with `player_label` plus `player_label_kind` (`proper_name | descriptor`) so the visible roster can mirror the backend secrecy contract directly instead of treating the extra fields as opaque. The scene-transcript backend pass also adds optional `scene_number_snapshot` / `scene_label_snapshot` / `scene_status_snapshot` mirrors on `OracleOutcome`.
- `web/src/styles/app.css`: bespoke pigment palette (`--ink-*`, `--paper-*`, `--gold-*`, `--rust-*`), three-voice type system (Cormorant body / IM Fell display / Alagard pixel engine voice), parchment + iron surfaces, deckled-edge SVG mask, film-grain overlay, button/form/tag styling. Adds a `.tag--cairn` flavor (verdigris-green tinted) for receipt strips of Cairn-flavored outcomes.
- `web/public/fonts/alagard.ttf`: CC-BY pixel font by Hewett Tsoi, used for the engine voice. VT323 is the Google-Fonts fallback.
- `web/src/components/`: `StatusStrip`, `SystemMenu`, `SaveLibrary`, `CharacterSetup`, `CharacterTemplateCard`, `CharacterEditor`, `LoadingPanel`, `CharacterFolio`, `CairnReadout`, `ChatFeed`, `ChatMessage`, `MessageActions`, `MechanicalReceipt`, `CombatTracker`, `Composer`, `EndBanner`, `Inspector`, `ChaosDial`, `Drawer`, `ThreadsPanel`, `NPCsPanel`, `NotesEditor`. `CairnReadout.svelte` is the shared read-only mechanics surface used by `CharacterFolio` (active play) and `CharacterEditor` (post-backfill draft preview). F-05 layered an ambush cue across `StatusStrip` (kicker swap + tint), `CombatTracker` (rust-blood `Ambush` flag), and `MechanicalReceipt` (strip tag swap + rust-blood rail + Cairn `Initiative` row) without inventing new components. H-01/H-02 extend those existing components rather than introducing new navigation chrome: `NPCsPanel.svelte` now renders descriptor-visible figures by `player_label` with a `known by sign` pip, `MechanicalReceipt.svelte` renders compact continuity pills for touched threads / visible figures, `Drawer.svelte` accepts a `reopenToken` one-shot reopen nudge, and `Inspector.svelte` / `ChatMessage.svelte` / `ChatFeed.svelte` now thread enough current-state context through the receipt path for those pills to deep-link into the existing Inspector surfaces. The `/ask` split reuses those same OOC chat surfaces rather than adding a new component: `ChatFeed.svelte` and `history.ts` now treat `oracle_preview` notes as verdigris OOC cards/searchable ephemeral notes alongside `explanation`. F-12 added two new components: `SystemMenu.svelte` (top-right hamburger dropdown with `Save library` / `Switch save` / `Begin a new campaign`, mounted on both the play `StatusStrip` and the skeleton strip used during character creation) and `SaveLibrary.svelte` (parchment-deckle card-grid splash that doubles as the empty-shelf frontispiece and the mid-session selector). Removed in the chat-first pivot: `SceneCard`, `OracleConsole`, `PlayerCommand`, `ActionLog`, `DiceTumbler` (the dice now live inline in `MechanicalReceipt`).

## Package Management

User preference: use `uv` for Python package management unless the project already has another package manager in place.

Because no code project exists yet, new Python setup should default to `uv`.

The project now uses `uv` with dependencies declared in `pyproject.toml`.

## Type Safety Expectations

For Python code, enforce maximal type safety:

- Full type annotations for public and private functions
- Strict optional handling
- Precise generics and protocols where useful
- No implicit or explicit `Any`
- Runtime validation where static typing cannot guarantee correctness
- Strict mypy or pyright configuration once the app exists

## Model Constraints

Do not change the selected LLM or public API signature unless the user explicitly asks. The current selected narrative model is OpenRouter Kimi K2.6 through LiteLLM:

- `LITELLM_MODEL=openrouter/moonshotai/kimi-k2.6`
- `OPENROUTER_API_KEY` loaded from `.env`
- `OPENROUTER_API_BASE=https://openrouter.ai/api/v1`
- `LITELLM_REASONING_EFFORT=auto`
- `LITELLM_EXCLUDE_REASONING=false`
- `LITELLM_NARRATION_TEMPERATURE=1.25`
- `LITELLM_NARRATION_MAX_TOKENS=4500`
- `LITELLM_TIMEOUT_SECONDS=600`

OpenRouter's model card lists the underlying model slug as `moonshotai/kimi-k2.6`, with 262K context and reasoning token support. LiteLLM uses the provider-prefixed model string `openrouter/moonshotai/kimi-k2.6`. The app defaults to a medium/high task-based reasoning policy instead of `xhigh`, because excessive thinking may make the model overcomplicate or hallucinate.

Older `LITELLM_TEMPERATURE` and `LITELLM_MAX_TOKENS` names still load as fallbacks for backward compatibility, but the typed config layer now treats them as deprecated narrator-only aliases rather than as shared task budgets.

## Testing Expectations

The user's standing testing preference is broad:

- Unit tests
- Integration tests
- End-to-end tests
- Manual testing instructions
- Manual browser testing using Pinchtab when applicable

For a Streamlit app, expect manual UI testing in a browser once the app can run.

Current verification commands:

- `uv run ruff check .`
- `uv run mypy src tests`
- `uv run pytest` (full backend suite currently passing)
- `uv run dungeon-master-backfill --json` (one-time save audit, dry-run by default)
- `uv run dungeon-master-fixtures --state-path "/tmp/dungeon-master-fixtures/game_state.json" --force --json` (seed an isolated fixture save library for browser/manual smoke)
- Focused F-06 backend verification: `uv run pytest tests/test_service.py tests/test_api.py -q` (77 passing), `uv run ruff check src/dungeon_master/models.py src/dungeon_master/service.py src/dungeon_master/api.py tests/test_service.py tests/test_api.py`, `uv run mypy src tests`, plus `uv run pytest -q` for the full backend suite. One test-harness hardening landed incidentally: `tests/test_service.py::CountingNarrative` now carries an inert `_config = NarrativeConfig(model="", api_key=None, base_url=None)` so the real thread updater never inherits live env model settings during regenerate-path tests.
- Focused reload-survives-streaming / observability verification: `uv run pytest tests/test_api.py tests/test_turn_router.py tests/test_continuity_classifier.py tests/test_narrative.py` (80 passing at the time of landing), plus strict mypy over the touched backend files and tests. New coverage asserts: detaching then reattaching a streamed turn still reaches `final_state`, reattach is rejected for the wrong active save, `TurnRouter` and `ContinuityClassifier` each emit one trace verdict line, and `_completion` emits an `llm.call` line with route/profile/token metadata.
- Focused frontend reload-survives-streaming verification: `cd web && npm run check`, `cd web && npm test -- --run` (233 passing at the time of landing — 8 new helper cases in `web/src/lib/stream-resume.test.ts` and 5 new bootstrap-resume integration cases in `web/src/lib/store-stream-resume.test.ts`), and `cd web && npm run build`. The new coverage asserts the per-save `localStorage` round-trip, TTL eviction, corrupt-row eviction, mismatched `save_id` eviction, descriptor write on `meta` + clear on `final_state`, descriptor preservation on server-aborted streams, bootstrap calling `api.reattachStream` and surfacing `streaming.resuming = true`, no reattach on cold start, and silent eviction on a 404 from the reattach endpoint.
- `cd web && npm run check`
- `cd web && npm test`  (Vitest — currently covers `lib/slash.ts`, `lib/character.ts`, `lib/message-actions.ts`, `lib/quiz.ts`, `lib/cairn.ts`, `lib/streaming.ts`, `lib/combat.ts`, `lib/cancel.ts`, `lib/threads.ts`, `lib/npcs.ts`, and the runes-based `lib/store.svelte.ts`; 131 passing — F-05 added ambush headline / `enemyInitiated` / adapter-mapping cases in `combat.test.ts` and harm-headline rewrite / `formatCombatInitiator` / `isAmbushOpener` cases in `cairn.test.ts`)
- `cd web && npm run build`
- `uv run dungeon-master` (backend) + `cd web && npm run dev` (frontend) for browser smoke tests via Pinchtab. Note: Pinchtab's `browser_fill` and `browser_type` set the DOM `value` attribute but do not always dispatch the `input` event Svelte 5's `bind:value` listens for; for end-to-end UI verification use a real keyboard, or rely on the slash-parser unit tests + the API integration tests to lock in the routing contract.
- Fixture-stack manual smoke path: `uv run dungeon-master-fixtures --state-path "/tmp/dungeon-master-fixtures/game_state.json" --force`, then `DUNGEON_MASTER_STATE_PATH="/tmp/dungeon-master-fixtures/game_state.json" uv run dungeon-master --port 8001`, then `cd web && VITE_API_PROXY_TARGET="http://127.0.0.1:8001" npm run dev -- --port 5174`.
- Backend-only Cairn smoke: `POST /api/cairn/save`, `/api/cairn/attack`, `/api/cairn/harm`, `/api/cairn/recover`, `/api/cairn/retreat`, `/api/cairn/acquire`, and `/api/cairn/equip` now exist and return the full `GameState`.
- Dynamic thread and NPC updates do not add new API routes. They flow through the existing oracle/turn endpoints because `GameService` now runs both updaters before turn checkpointing and narration, and the full returned `GameState` already includes the updated thread/NPC canon.
- Enemy-first / ambush combat also does not add a new API route in F-05. It flows through `/api/turn` via the planner's internal `enemy_opener` op and reuses the existing `harm` outcome kind plus `state.encounter` for the public wire contract.
- Campaign ending does add a new API route in F-06: `/api/campaign/end` for explicit retirement/victory (and validated death if ever needed for repair/admin flows). Automatic death endings still flow through the existing turn/cairn routes because the service finalizes terminal state inside the ordinary commit path.

## Operational Requirements

The source and user preferences imply the following reliability requirements:

- Parallelize independent I/O where applicable.
- Add retries around LLM and external API calls.
- Implement checkpoints so failed turns can be recovered.
- Keep canonical state outside the LLM context window.
- Keep compacted continuity memory outside canonical state, in a rebuildable sidecar, so prompt-bounding does not pollute the source-of-truth save format.
- Prefer deterministic tools and typed outputs over unconstrained prose.
- Make the oracle engine roll internally and emit strict typed results.
- Prevent the narrative engine from changing state or rolling dice.
- Use the model for structured interpretation tasks (turn classification, one-time mechanics backfill) instead of keyword/regex inference.

## Known Technical Risks

- Frontend types are hand-mirrored from Pydantic models. If the API surface drifts, the frontend will fail at runtime, not build time. Acceptable for a personal project; revisit with codegen if churn becomes painful.
- LangGraph or any formal graph framework remains optional. The current `GameService` is enough for the deterministic loop.
- Copying proprietary Mythic GME 2e tables verbatim may create licensing issues; prefer original tables, user-supplied licensed material, or open alternatives.
- Raw local files are simple but need careful locking or transaction semantics if concurrent actions are ever added (single-user assumption keeps this fine for now).
- The dice-tumble animation assumes the API returns within a few seconds; very slow models will leave the dice spinning. The backend exposes streamed progress / reasoning for both setup and play over NDJSON, and the frontend store / chat / inspector all consume that surface; the dice now tumble between `meta` and the first `content_delta` rather than blocking on a full response.
- Kimi K2.6 Thinking effectively spends ~2-3k tokens on reasoning regardless of the requested `effort` setting, so character/campaign generation endpoints need large token budgets (`max_tokens=12000`) or they silently truncate JSON.
