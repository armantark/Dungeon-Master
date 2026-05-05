# Active Context

## Current Focus

The active task has moved from planning to building a fully fledged personal agentic TTRPG/AI game-master system.

The most recent source-note state is:

- The user is not committed to OSR.
- OSR entered the discussion only because it appeared in a Discord server description.
- Earlier AI exploration leaned Mythic GME-style, but the user clarified those were exploratory assumptions rather than approved direction.
- The newly chosen direction is a **Cairn 2e-inspired dark-fantasy adaptation** with more structure than the current fiction-only sheet.
- The user wants the experience grounded in rules and explicitly said the system should "tickle my TiNeSiFe fancy" — internal coherence, enough mechanical structure to feel game-like, and meaningful inventory/stats without becoming a bloated engine.
- The Streamlit UI was discarded; a bespoke Svelte 5 grimoire UI replaces it.
- The frontend will live only on the user's machine and at most on their personal GitHub. No public hosting is planned.
- The Svelte UI is **chat-first**, not a dashboard. The conversation is the product; mechanics are evidence on demand. The original three-column ledger (SceneCard / OracleConsole / PlayerCommand / ActionLog / sidebar drawers) was deleted.
- The pixel font **Alagard** is the visual voice of the engine: it's used for the chaos numeral, scene numeral, dice readouts, oracle tags ("YES NO", "RANDOM EVENT", "SCENE CHECK"), kicker labels, system messages, and inspector controls. Cormorant Garamond stays the narrative voice; IM Fell English SC stays the display / scene-head voice. The three voices never mix.

The current code state is:

- FastAPI backend at `src/dungeon_master/api.py`, started by `uv run dungeon-master`.
- Core game package code lives under `src/dungeon_master/`.
- Canonical state persists to `data/game_state.json`.
- Event history persists to `data/events.jsonl`.
- Checkpoints persist under `data/checkpoints/`.
- Derived GM-note memory now persists separately to `data/memory.json`.
- Bespoke Svelte 5 + Vite + TS frontend lives in `web/`, with vanilla CSS and the "Oracle's Ledger" aesthetic.
- Frontend layout is: top status strip (`StatusStrip.svelte`) → flowing chat column (`ChatFeed.svelte` + `ChatMessage.svelte` + `MechanicalReceipt.svelte`) → sticky composer (`Composer.svelte`); inspector drawer (`Inspector.svelte`) slides in from the right edge holding `ChaosDial`, threads, NPCs, notes, and full oracle history.
- A persistent left `CharacterFolio.svelte` now sits beside the chat on desktop widths. It shows the structured character sheet, condition, and inventory so identity/gear stay available during play without opening the inspector.
- The inspector is now a compact reference drawer, not a nested-scroll dashboard. All reference sections are collapsed by default, chaos is a tight control row instead of the large wax seal, drawer bodies are height-capped, and long thread/NPC text is line-clamped.
- Campaign flow now has an explicit setup lifecycle: `character_creation` -> `ready_to_start` -> `active`. New sessions no longer auto-generate a world on first load; they enter `CharacterSetup.svelte` first.
- Character creation now supports three flows: archetypal AI templates, blank scratch sheet, and an **AI-assisted interview** ("assist") path. The assist path is now multi-step: the player types a one-line concept, the LLM generates a 4–6 question interview tailored to that concept (each question has 3–5 options + a free-text "Other (write your own)"), the player answers, an optional "Anything else?" review note is collected, and only then is the draft generated from concept + answers + final note. Every generation phase shows a `LoadingPanel.svelte` indicator with a same-place cancel control.
- LLM token budgets for character generation: Kimi K2.6 Thinking always burns ~2-3k reasoning tokens regardless of the requested `effort` setting, so the previous 2200/2400-token caps were silently producing zero content (`finish_reason=length`, `content=None`). All character/quiz/draft requests now use `medium` reasoning + `max_tokens=12000`; campaign generation keeps `high` reasoning but with the same 12000 budget. Quiz generation uses `low` reasoning specifically because it's structured authoring with short strings.
- All generation fallbacks now log via `logger.exception` so silent fallbacks (the old "draft looks generic / templated") are visible in the uvicorn logs instead of disappearing into the network.
- Latest DM response now gets a `Regenerate response` button. Regeneration restores the pre-narration checkpoint for that turn, preserves the deterministic oracle outcome/dice, and appends a system audit event before writing the repaired narrative.
- The client `Stop` button is now wired to true server-side cancellation. `web/src/lib/api.ts` exposes `cancelRequest(requestId)` (POST `/api/requests/{id}/cancel`); the store's `cancelCurrentRequest` fires that endpoint fire-and-forget BEFORE aborting the local fetch (so the registry sees the id while the connection is still live), clears the provisional streaming buffer up-front, and idempotently no-ops on subsequent presses while the abort is still draining. Backend `discard-only` semantics mean the in-flight turn's events and checkpoint are never persisted on cancel.
- Backend streaming is no longer limited to narrative turns. All model-backed setup flows now share the same NDJSON contract: a `meta` line first (carrying `request_id` + `route`), then `thinking_delta` / `content_delta` lines, then exactly one terminal `final_state` (full `GameState` streams: turn, action, regenerate, campaign start) or `final_payload` (setup artifacts: templates / quiz / draft, with `kind` + `payload` + `thinking`). Errors land as a single `error` line so the frontend can branch on `result.kind === "error"` without parsing partial-state HTTP failures.
- `GameService` now exposes result-bearing and streaming setup methods (`list_character_templates_result`, `generate_character_quiz_result`, `generate_character_draft_result`, `generate_quizzed_character_draft_result`, `start_campaign_result`, plus matching `stream_*` methods). The HTTP layer in `src/dungeon_master/api.py` runs them through `_stream_game_state` / `_stream_setup_payload` helpers that own the NDJSON envelope and `Content-Type: application/x-ndjson`.
- **Backend server-side cancellation now exists.** `src/dungeon_master/cancel.py` introduces a process-local `CancellationRegistry` + `CancellationToken`; `src/dungeon_master/api.py` registers one token per streamed request, emits the request ID in `meta`, exposes `POST /api/requests/{request_id}/cancel`, and closes the stream cleanly on cancellation instead of surfacing it as an error.
- **Discard-only streamed persistence is now enforced in the backend.** `GameService` defers streamed turn checkpoints and event-log writes until the final commit path, re-checks cancellation before those writes, and batches event-log appends. If a stream is cancelled before commit, the turn's player/oracle/narrative events are never appended to `events.jsonl` and `game_state.json` is left unchanged.
- **Cancellation now threads through model work, not just the HTTP wrapper.** `CompletionRequest` carries an optional `cancel_token`, `narrative.py` checks it while consuming LiteLLM streams, and the streaming setup / router / encounter paths in `campaign.py`, `turn_router.py`, and `cairn.py` pass that token through so classification, setup generation, encounter seeding, and narration all stop cooperatively.
- A small backend-only latency improvement also landed: `GameService.submit_player_turn` / `stream_submit_player_turn` now overlap state loading with turn routing in a worker thread so disk I/O and the router's model call are not needlessly serialized.
- Frontend transport is in `web/src/lib/streaming.ts` (`consumeStream`) and `web/src/lib/streaming-types.ts` (the discriminated event union). The store (`web/src/lib/store.svelte.ts`) consumes streams via `#runStreaming` (state-mutating endpoints) and `#runStreamingPayload` (setup endpoints), with a transparent fallback to the unary endpoint when the streaming variant returns 404/405. ChatFeed renders a provisional DM bubble bound to `streaming.content`/`thinking`/`pendingOutcome` while a stream is active.
- `web/src/lib/combat.ts` is the read-only adapter from the canonical backend `EncounterState` (under `GameState.encounter`) to the tracker's richer per-foe shape (`status` derived from defeated/fled/critically_wounded; `morale_triggered` derived from the encounter's casualty/half-force flags; backend `description` rendered as a single tag chip). The adapter intentionally lives outside `types.ts` because the backend wire shape and the tracker's display shape are not 1:1; promoting `encounter` into `types.ts` is a follow-up if other components ever need to read it directly.
- Player input has two routing layers:
  - Explicit slash commands are parsed by `web/src/lib/slash.ts`: `/ask <q> [hint]`, `/event`, `/scene <body>`, `/chaos <n>`, `/reset`, `/help`, and `/retreat [reason]` (with `/flee` and `/disengage` aliases). Slash hints are unit-tested in `web/src/lib/slash.test.ts` (Vitest). The composer now also surfaces a slash suggestion menu (Up/Down to navigate, Tab/Enter to complete, Esc to dismiss) backed by a `SLASH_COMMANDS` descriptor list so `/help` and the menu read from a single source. `/retreat` is wired through the regular turn pipeline (translated to a free-text turn "I attempt to retreat from combat[: <reason>]") so the planner classifies it, the narrator runs, and memory updates uniformly — the explicit `/api/cairn/retreat` endpoint exists but is reserved for future deterministic-only callers.
  - Bare chat is sent to backend `/api/turn`, where `src/dungeon_master/turn_router.py` now emits a bounded **typed action plan** instead of only a single route label. The plan still carries a legacy summary `route` for compatibility, but can now express ordered prep steps like `inspect_inventory`, `search_scene`, `use_item`, `drop_item`, and `equip` before one primary oracle/mechanical action. `GameService` executes the validated plan in Python, then hands the narrator both the final `OracleOutcome` and a concise executed-step summary so prose stays grounded in what actually committed.
- `web/public/fonts/alagard.ttf` (CC-BY) is committed locally; `VT323` from Google Fonts is the auto-fallback if the file is missing.
- `GameState.character` now holds both the narrative sheet and a nested Cairn 2e-inspired mechanics block. Old saves remain compatible: missing character sheets are seeded from `player_notes`, and active/current characters with `cairn.source == "unset"` are one-time backfilled into structured stats/equipment on load or campaign start.
- `CharacterSheet` now carries: `name`, `archetype`, `epithet`, `backstory`, `drive`, `flaw`, `condition`, `inventory`, and nested `cairn` mechanics state. `InventoryItem` now also carries nested `cairn` item semantics (slots, tags, weapon die, armor bonus, uses, equipped).
- There is now a dedicated backend rules engine in `src/dungeon_master/cairn.py`. It owns one-time backfill, save resolution, outgoing attacks, incoming harm/critical damage/scars, recovery, equipment toggles, and derived armor/burden state.
- FastAPI now exposes backend-only Cairn endpoints in addition to the oracle routes: `POST /api/cairn/save`, `/api/cairn/attack`, `/api/cairn/harm`, `/api/cairn/recover`, and `/api/cairn/equip`.
- `TurnRouter` still uses LiteLLM-backed structured interpretation instead of regex-based inference, but the unit of work is now a bounded **plan** rather than a single coarse route. The compatibility `route()` wrapper still exists for old tests/callers, while `GameService.submit_player_turn` / `stream_submit_player_turn` now call `plan()` and execute the ordered ops. If planning is unavailable, the backend degrades to a one-step `player_action`/`narrate` plan rather than guessing.
- `src/dungeon_master/memory.py` now defines the tiered derived-memory layer. It stores compacted `recent_turn_summaries`, `scene_summaries`, `thread_memory`, `npc_memory`, `location_memory`, `revealed_facts`, `open_loops`, and `callback_candidates`, and renders bounded retrieval blocks for the planner and narrator.
- `GameService` now rebuilds and saves the derived memory sidecar after committed state saves, and loads/syncs it before planner/narrator calls so prompts receive compact GM-note context instead of raw log replay.
- The memory retrieval layer is intentionally **not** driven by hardcoded lexical stopwords or token-overlap heuristics. After a brief implementation drift in that direction, it was corrected to use canonical links already present in state/outcomes, scene locality, active status, recency, and compacted cards.
- The bug-fix pass after the initial memory rollout is now in progress/completed in code: streamed turns capture a true pre-narration checkpoint for regenerate, turn checkpoints carry `execution_context`, `GameService` rebuilds memory from exact committed-turn metadata rather than lossy `action_log` indexing, planner failures surface explicitly instead of silently degrading to narration, planner memory now includes query-aware canonical context plus carried gear, regenerate receives the same memory context as normal turns, and the setup-stream store path surfaces server-aborted generation as an error.
- There is now a persistent feature backlog board at `memory-bank/featureKanban.md`. The latest product decision is to work ticket-by-ticket from that board in plan mode rather than attempting one giant feature bundle.
- `F-01 Retreat / Disengage` backend pass is now landed. The backend can route and resolve a canonical `retreat` action, track `caught | disengaged | escaped` outcomes, preserve pursuit/disengaged encounter state, and expose an explicit `/api/cairn/retreat` endpoint. Minimal frontend compatibility for the new outcome kind/receipt headline also landed, but the actual player-facing discoverability/affordance work for retreat remains a later frontend pass.
- `CairnEngine` gained additional deterministic inventory mutations to support the planner's non-combat action vocabulary: `use_item` and `drop_item` now live beside `set_item_equipped`, keeping burden / armor / primary-weapon derivation centralized in the rules engine instead of scattering inventory edits through `GameService`.
- The Cairn backfill path is now also LLM-backed. `CairnEngine` no longer infers stats or item semantics from keyword matching; it asks the model for a structured mechanics record plus a practical starting bundle. This was changed because the earlier inference path over-literalized flavor into gear (`myrrh jaw` -> `jaw bindings`) and produced items that felt more symbolic than playable.
- Cairn here still does not mean a D&D-style skill tree. The structured layer is `STR`, `DEX`, `WIL`, HP, burden, item tags, and short textual `skills` / `abilities` that represent specialties or permissions rather than numeric modifiers.
- Tests under `tests/` now cover the oracle, state store, narrative engine, service, turn router, Cairn backfill/mechanics flows, and FastAPI routes (including the new Cairn endpoints); `web/` tests still cover the slash parser, character helpers, message regeneration gate, and the quiz answer builder/validator (`web/src/lib/quiz.test.ts`).
- Manual browser testing instructions exist at `docs/manual-testing.md` (now a product walkthrough; env knobs moved to a short developer-knobs appendix).
- Campaign opening content and oracle word banks are generated at campaign initialization rather than baked into `models.py` or `oracle.py`.
- The first Cairn frontend pass is implemented: the persistent folio renders HP / STR / DEX / WIL, a segmented burden meter, fatigue, priority-ordered status chips, skills/abilities, equipped + primary-weapon badges, and per-item tag chips with weapon-die / armor-bonus / uses / slots readouts. `MechanicalReceipt` is exhaustive over the new `save | attack | harm | recovery` kinds and renders structured Cairn fields in the body. The inspector adds a collapsed "Cairn build notes" drawer over the LLM-authored backfill rationale. The character editor surfaces the read-only Cairn block above the parchment editor only when the draft already has derived mechanics.
- The folio rail is now genuinely two-column on any non-tiny window: width is `clamp(296px, 40vw, 720px)` so it grows aggressively into the gutter past the chat's 72ch cap, and `CharacterFolio.svelte` introduces a `.folio__layout` inner grid wrapper plus two `.folio__col` flex columns. The outer `.folio` element carries `container-type: inline-size` and `container-name: folio` (this nesting is required because container queries cannot restyle the container element itself, only descendants — putting the grid template directly on `.folio` was a no-op until the inner wrapper was added). At `@container folio (min-width: 280px)` the layout flips from a 4-row single column into an identity-on-the-left / ledger-on-the-right split: the left column carries the plate (epithet + name + backstory) and the full Condition / Drive prose with no line clamp; the right column carries the Cairn mechanics readout above the inventory list, with the inventory still scrolling internally. In the narrow fallback the columns collapse via `display: contents` so the four sections flow as direct grid children of `.folio__layout` and use the original vertical stack with a 3-line clamp. A vertical rule between the columns replaces the inter-section horizontal rules in wide mode so they don't strand above empty space at the bottom of the shorter (identity) column. Container queries (rather than viewport media queries) were chosen because the rail's logical width is also clamped by the chat column and does not always track the viewport.
- The frontend deliberately does **not** yet call `/api/cairn/attack`, `/harm`, `/recover`, or `/equip`. Those endpoints remain live but unbound until the explicit-controls pass. There are also no Cairn-specific slash commands; the existing LLM-backed `/api/turn` router still classifies free text into the `save` route transparently.
- **Live LLM playability landed.** Two empirically-discovered Kimi K2.6 / OpenRouter pitfalls were fixed:
  - Setting `response_format={"type":"json_object"}` causes Kimi K2.6 to over-deliberate (we measured 335s vs ~30s for the same prompt without it). Every JSON-shaped call (`TurnRouter`, `CairnEngine.backfill` / encounter seed, every `CharacterGenerator` / `CampaignGenerator` step) now drops `response_format` and runs the JSON output through `narrative.extract_json_object`, which strips ```json fences and isolates the first balanced `{...}` block before Pydantic validation. All those calls also now stream (`stream=True`) — Kimi K2.6 reliably returns content under streaming but sometimes returns `content=None` in unary mode when reasoning fully consumes `max_tokens`.
  - `reasoning.effort` and `reasoning.max_tokens` are mutually exclusive on OpenRouter ("Only one of \"reasoning.effort\" and \"reasoning.max_tokens\" can be specified"). We now pass only `reasoning.max_tokens` (deterministic budget control) and let the top-level `reasoning_effort` alias remain for OpenAI-compatible providers via LiteLLM's `drop_params=True`. Per-task reasoning caps: 600 tokens for the turn router classifier, 1200 for the encounter seed, 1500 for routine narration, 3000 for scene/random-event narration. Narrative `max_tokens` was raised from 1800 → 4500 because Kimi reliably burns 2-3k reasoning tokens regardless of effort and the smaller cap was producing empty content (and silently triggering the deterministic fallback narration).
- **Realistic per-turn latency budget on Kimi K2.6.** Live smokes against the real model now show ~2-3 minutes for a routine narration turn and ~3-5 minutes for a combat turn that also seeds a new encounter. Reasoning is no longer hidden by default (`exclude_reasoning=False`) so the UI can stream a live "thinking..." indicator while the model deliberates instead of presenting a frozen viewport. Set `LITELLM_EXCLUDE_REASONING=true` to opt out for unit-test runs or cheaper sessions.
- **Inventory name fuzzy-matching.** `_item_id_from_name` in `service.py` now does token-overlap matching (length-≥3 word tokens) in addition to substring containment, because the LLM-backed router routinely abbreviates item names ("notched cudgel" instead of "Notched iron cudgel") and the previous strict containment match failed those calls with a 409.
- **Narrative prompt tightened for compact, better-grounded responses.** `src/dungeon_master/narrative.py` no longer asks for `1-3 paragraphs`; it now asks for `1-2 compact paragraphs, usually 1`, explicitly tells the narrator to mirror the player's declared action before extending the scene, and forbids hardening item flavor / latent threats / atmospheric details into present-tense facts unless the supplied oracle outcome or canonical state licenses them. The prompt also prefers one concrete follow-up question over a dramatic branch menu.
- **Restored `data/game_state.json` to its first-message state.** The Vrtanes save was rolled back to the campaign-init checkpoint (HP/STR/DEX/WIL maxed, encounter cleared, oracle history empty, only the `Campaign initialized` event remaining). Pre-rollback copies are kept under `data/backups/*before_first_message_reset_*`. The reset script lives at `/tmp/dm-restore.py` and is reproducible if ever needed again.

## Current Decision State

Settled:

- Build around deterministic state management, not raw LLM memory.
- Treat the LLM as a creative and interpretive component, not the canonical source of truth.
- Keep checkpoints and structured state updates central to the design.
- Preserve the raw source note as source material.
- Replace Streamlit with a FastAPI backend + a bespoke Svelte 5 grimoire UI.
- Use plain Svelte 5 + Vite + TypeScript (no SvelteKit) since the app is single-page and single-user.
- Use vanilla CSS with custom properties (no Tailwind) so the parchment / iron / wax-seal aesthetic does not get homogenized by utility classes.
- Make the Svelte UI chat-first: a single conversation column is the primary surface, and mechanical state lives in a peek-on-demand inspector drawer rather than a permanent dashboard.
- Use slash commands (`/ask`, `/event`, `/scene`, `/chaos`, `/reset`, `/help`) for explicit oracle invocation, but route bare natural-language input through backend `/api/turn` so obvious questions and scene transitions can trigger mechanics automatically. Slash commands remain the manual override path.
- Treat `.env` knobs as developer / debug controls, not user-facing settings. If a switch ever feels like it should be on the UI, that's a signal to promote it to a real control.
- Use Alagard (pixel) as the engine voice and Cormorant Garamond as the narrative voice; the two never mix on the same string of text.
- Prefer a deterministic oracle engine over a full RPG rules engine.
- Use original deterministic oracle tables; do not copy proprietary Mythic GME 2e text.
- Use LiteLLM for model switching.
- Use OpenRouter Kimi K2.6 as the selected narrative model.
- Use task-based reasoning via `LITELLM_REASONING_EFFORT=auto`: medium for ordinary narration/yes-no turns, high for scene checks and random events.
- Read the user's OpenRouter key from `OPENROUTER_API_KEY` in `.env`.
- Keep the LLM narrative client optional; the app falls back to deterministic placeholder narration when no compatible endpoint is configured.
- Bind the FastAPI server to `127.0.0.1` only — this is a personal-machine app.
- Mirror Pydantic types by hand in `web/src/lib/types.ts` instead of running OpenAPI codegen.
- The next mechanics layer should be **Cairn 2e-inspired rather than pure oracle-only**.
- The Cairn layer should be **more structured than not**: canonical stats/HP/burden/equipment tags, deterministic roll logic, and mechanical inventory effects should live in typed state and Python logic rather than being left to narrative inference.
- Stats and gear mechanics for the current character should be **automatically backfilled** from the existing authored character sheet and generated opening scene; the user does not want to redo character creation.
- Do not use rule-based keyword/regex inference where LLM-backed structured interpretation is more appropriate. Deterministic systems stay deterministic (dice, explicit endpoints, slash commands, save math, damage math), but interpretation/backfill/routing should use the model.
- The backend cancellation contract is **discard-only**. If Stop wins before commit, that turn did not happen: no canonical event log entry, no state mutation, no terminal NDJSON payload.

Open:

- Whether to refine the original oracle tables or replace them with user-supplied licensed/open material.
- Whether the lightweight service layer is enough or a formal graph framework should be added later.
- Whether to add a UI text box for user-authored campaign seeds before generation.
- Whether to expose model switching controls in the UI instead of keeping them environment-only.
- Whether to add checkpoint browse / rollback controls to the frontend.
- Whether the Cairn-inspired layer should stay close to Cairn 2e as-written or deliberately bend farther into a custom dark-fantasy adaptation once the first backend implementation lands.
- Whether to expose the already-streamed model reasoning/thinking in a collapsible frontend panel during setup/play, and exactly where that panel should live.
- How much of Cairn combat should be automatically inferred from free-text turns versus left as explicit API/UI actions. The backend can now classify free-text turns into `attack`, `harm`, `recovery`, and `equip` in addition to `save`, and real enemy combatant state is persisted canonically, but the frontend still needs the explicit-controls / combat-surface pass.
- Whether the new memory sidecar should later gain a richer semantic reranker or vector-backed retrieval backend once long-form campaign play reveals actual recall gaps. The storage and prompt seams now exist, so that can be upgraded without rewriting the whole system.
- **TOON (Token-Oriented Object Notation, https://github.com/toon-format/toon) as a possible LLM-input optimization.** TOON is a YAML/CSV-hybrid encoding of the JSON data model that benchmarks ~30-40% fewer tokens than JSON for uniform arrays of objects, while keeping a `[N]{fields}:` schema header that LLMs parse reliably. Earmarked, **not adopted**. The decision boundary is:
  - Keep JSON / Pydantic for canonical state, persisted files, the HTTP wire format, the NDJSON streaming envelope, and any structured *output* we expect the model to produce — our type/validation pipeline is built around JSON and we deliberately do not want the model authoring a custom DSL.
  - The candidate use is TOON-encoding *prompt input only*, specifically the parts of `GameState` that are uniform-arrays-of-objects: inventory, NPCs, threads, oracle word banks, encounter combatants, and possibly recent slices of `action_log` / `oracle_history`. These are exactly the shapes TOON is designed for.
  - Our current latency dominator is Kimi K2.6's reasoning time, not prompt verbosity, so TOON is unlikely to be a silver bullet here. Before committing, we'd want a real before/after benchmark on `TurnRouter`, `CairnEngine` encounter seeding, and `NarrativeEngine` prompts measuring prompt tokens *and* end-to-end turn latency.
  - If we ever do adopt TOON, scope it as an internal `prompt_format.py` adapter that encodes selected `GameState` slices for prompt assembly only; do not let it leak into models, tests, or persistence. Current Python implementations exist; pin one rather than vendoring.

## Important User Preferences

- The desired game tone is traditional, gritty, oppressive dark fantasy, and apolitical, with a vibe closer to `Berserk` or `Fear & Hunger`.
- The user wants to avoid social friction from public Discord or local groups.
- The user is interested in software architecture that solves LLM reliability problems.
- The user values strong state tracking, retries, and checkpointing.
- The user prefers not to waste energy on dead communities or excessive setup.
- The user is comfortable with Cursor doing substantial scaffolding.
- The user wants a serious personal enjoyment project, not a business-client MVP. Avoid bloat, but do not underbuild for the sake of artificial minimalism.
- The user does **not** want exploratory AI assumptions treated as approved product direction.
- The user wants rules that feel grounded and structured enough to be satisfying, not just a pure oracle fiction loop.

## Recent Learnings From Source Note

- West Marches means rotating-player sandbox campaigns where players schedule expeditions from a safe home base.
- OSR means old-school tabletop play with rulings, high lethality, resource management, and player ingenuity.
- Tabletop Simulator is a digital table, not a matchmaking solution or rules engine.
- Solo TTRPGs are closer to oracle-guided creative play than CRPGs.
- LLM game-mastering becomes viable only if state and mechanics are externalized.
- The proposed application should borrow the useful parts of solo TTRPGs and CRPGs without inheriting their biggest drawbacks.
- Mythic-style oracle mechanics are a better first fit than OSR because they are solo-first, system-agnostic, and deterministic.
- The app should expose buttons for asking the oracle, generating random events, and checking scenes.

## Next Best Step

Next practical steps:

1. **Game is now playable end-to-end against the real Kimi K2.6 model with a compacted memory layer and the first bug-fix pass on regenerate/memory/planner failure behavior.**
2. Use `memory-bank/featureKanban.md` as the ticket queue and switch to plan mode per ticket as implementation begins.
3. `F-01 Retreat / Disengage` backend is complete; the next decision is whether to finish its frontend discoverability/affordance pass immediately or move to the next backend-heavy ticket (`F-02`, `F-03`, `F-04`, or `F-05`).
4. Measure the new `data/memory.json` retrieval quality over longer play and decide whether the current canonical/recency-bounded selection is sufficient or should graduate to a semantic reranker.
5. Optional enhancement: emit `mechanics_ready` *before* the first `content_delta` so the receipt strip pins ahead of the prose. The frontend already handles the event; the backend currently only attaches the outcome at `final_state`.
6. Further latency work: if combat turns still feel too slow after the memory pass, revisit the remaining sequential pre-narration LLM work (especially encounter seeding on the first attack of a fight).

## Caution

Do not overfit the app to Scarlet Heroes or OSR unless the user explicitly chooses that direction. The project is about a reliable AI-assisted game-master harness first; the oracle/rules layer should remain replaceable.

Also avoid copying Mythic GME 2e tables verbatim unless the user supplies licensed material or chooses an open alternative. The system can implement an original deterministic oracle with the same general roles: likelihood, chaos, scene pacing, events, threads, and NPC prompts.
