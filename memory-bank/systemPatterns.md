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
- **Backend turn planner** (`src/dungeon_master/turn_router.py` + `/api/turn`): bare natural-language chat goes here. It no longer emits only a single coarse route label. The backend now asks the model for a bounded **typed action plan**: 1-3 ordered steps drawn from a fixed vocabulary (`yes_no`, `random_event`, `scene_check`, `save`, `attack`, `harm`, `recovery`, `equip`, plus non-combat prep/state-adjacent steps like `inspect_inventory`, `search_scene`, `use_item`, `drop_item`, and `narrate`). The returned `route` is still the legacy summary label for compatibility, but `GameService` now executes the ordered plan rather than switching on one enum alone. Planner output is still validated through Pydantic, but because Kimi/OpenRouter previously showed pathological latency with provider-enforced `response_format=json_object`, the current reliability pattern is schema-aware repair: after malformed model output, the router sends the failed payload plus `GeneratedTurnPlan.model_json_schema()` through a low-temperature repair request and validates that result again. Only if both attempts fail does it degrade to a one-step `player_action`/`narrate` plan, which preserves the user's turn without guessing mechanics. Broad requests to seek/start/enter combat are treated as scene setup, not as `attack`, unless the player declares a concrete strike, target, weapon use, ambush, or incoming blow.
- **Backend `GameService`** (`src/dungeon_master/service.py`): receives a typed call (`ask_yes_no`, `random_event`, `scene_check`, `submit_action`, etc.) and runs the deterministic mechanics in the right order, never trusting the LLM with state mutation. The router fallback is intentionally safe rather than silent mechanical inference: a failed structured plan can still produce prose for the player's exact text, but it cannot invent a save, attack, item transfer, or other deterministic operation.

Planner operations / routes that currently exist:

- Narrative-only action (ambiguous free text / `/action`)
- Yes/no oracle question (`/ask`, or bare yes/no questions via `/api/turn`)
- Random event generation (`/event`, or "something happens" prompts via `/api/turn`)
- Scene setup check (`/scene`, or obvious movement transitions via `/api/turn`)
- Cairn save / attack / harm / recovery / equip
- Non-combat prep ops inside planned turns: inspect inventory, search the current scene, acquire an item/bundle, use an item, drop an item
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

The original implementation persisted canonical state to a single flat `data/game_state.json`, appended event log entries to `data/events.jsonl`, and wrote timestamped JSON checkpoints to `data/checkpoints/`.

F-12 now generalizes that into a **save-library + per-save directory** pattern without changing `StateStore` itself:

- `data/library.json` is the global manifest (currently: active save id + save record list).
- each save lives under `data/saves/<save_id>/`
- inside that directory the shape is still the existing `StateStore` contract: `game_state.json`, `events.jsonl`, `memory.json`, `checkpoints/`, `turn-checkpoints/`

F-16 adds one more state-manager split inside each save:

- `GameState.npcs` is now the **introduced / player-visible recurring roster**
- `GameState.hidden_npcs` is the backend-only hidden cast
- `npc_roster_version` gates a one-time repair path for pre-F-16 saves

This is intentionally not modeled as a single list with a frontend-only filter. The current frontend already renders `state.npcs`, so redefining that field as the introduced roster lets the existing UI stop showing spoiler NPCs immediately, while the backend still retains a hidden continuity cast separately. The service layer owns the migration: on load, a legacy save is repaired once, persisted with the new version, and future requests read the split state directly.

This is intentionally conservative. Rather than teaching every gameplay route about `save_id`, the FastAPI app still keeps one *active* `GameService` for v1 and simply rebinds that service to the selected slot's `StateStore`. That preserves the current "full `GameState` per request" frontend contract and postpones true multi-tenant route plumbing until it is actually needed.

There is now also a separate derived-memory sidecar at `data/memory.json`. This is **not** canonical state and is intentionally kept outside `GameState`:

- it is rebuilt from committed canon rather than treated as source of truth
- it holds the app's compacted "GM notes" (`recent_turn_summaries`, `scene_summaries`, `thread_memory`, `npc_memory`, `location_memory`, `revealed_facts`, `open_loops`, `callback_candidates`)
- it is written only after committed saves, so cancel/discard semantics remain intact
- it exists to keep planner/narrator prompts bounded without replaying raw logs
- it is disposable when malformed or stale: `StateStore.load_memory_or_none()` returns `None` for memory-sidecar validation failures so the service rebuilds it from canonical state/events/checkpoints instead of blocking play. This tolerance applies only to the derived sidecar; `game_state.json` and turn checkpoints still validate strictly.

The follow-up bug-fix pass tightened two important invariants around that sidecar:

- streamed turns now persist a captured **pre-narration** turn checkpoint, matching the unary regenerate contract instead of checkpointing a state that already contains the old DM response
- turn checkpoints now also persist `execution_context`, so memory rebuilds and regenerate calls can retain the exact deterministic backend-step summary that originally grounded the narration
- narrator prompt context now force-rebuilds from checkpoint-linked committed turns rather than trusting a schema-valid existing `memory.json` sidecar. This is load-bearing because a stale/corrupt derived sidecar can otherwise leak an old first-message or old location card back into `BOUNDED_MEMORY_CONTEXT` even when canonical `game_state.json` is correct. Streamed turns pass their in-memory pre-narration `TurnCheckpointRecord` as an override so the same invariant holds before the deferred checkpoint is written to disk.

One more memory pattern now exists on top of that sidecar: **scene transcript vs. campaign chronicle**.

- The active scene is no longer represented only as compact turn summaries. Each committed `OracleOutcome` now snapshots its scene number / label / status, and `MemoryManager` keeps a full `current_scene_turns` transcript for the still-open scene.
- Closed scenes are compacted into the existing `scene_summaries` list, which now acts as a rolling campaign chronicle rather than only a local note card list.
- Planner and narrator prompts now receive the active scene transcript as prepended chat history plus the prior-scene chronicle as compact continuity notes. This preserves short-horizon conversational referents ("who is speaking right now?") without replaying the whole campaign transcript every turn.
- Scene numbering is also no longer "scene check count." `GameService` only increments `scene_number` when the resolved scene label or status materially changes, so a same-scene confirmation does not silently create Scene 2.
- Active-scene summaries and current location cards prefer authoritative `GameState.current_scene` over older per-turn scene snapshot labels. Older snapshots remain historical turn metadata, but the narrator's live `CURRENT_SCENE`, `SCENE_SUMMARY`, and active location memory should describe where play actually is now.

F-12 adds one more state-manager invariant on top of the existing discard-only streaming contract: **the active save may not change while a streamed request is still live.** The cancellation registry is therefore no longer only a stop-button primitive; it also gates save switching. If any request remains registered, `POST /api/library/select` (and any create-and-select operation) rejects with a conflict rather than risking a turn that starts against save A and commits against save B.

The frontend mirrors that single-active-save invariant directly. The Svelte store (`web/src/lib/store.svelte.ts`) models a `LibraryStatus = "loading" | "empty" | "selecting" | "ready"` discriminated union, and the App layout routes through an exhaustive `loading | library-empty | library-selecting | setup | active | ended` switch. A library splash (`SaveLibrary.svelte`) owns the screen until the player resolves it; mid-session "switch save" enters the `selecting` mode without unbinding the current save, so the player can cancel out without a network round-trip. The single canonical store-side rule is that **every save switch flushes per-save client ephemera** — a small `#resetEphemera()` helper is called from both `createSave` and `selectSave` and clears `notes`, the in-flight provisional streaming buffer, the F-09 scroll request, the dice phase, and the local error sink. Cross-save bleed-through is impossible by construction. The hamburger system menu (`SystemMenu.svelte`) is mounted on both the play `StatusStrip` and the skeleton strip used during character creation / library splashes, so a fresh save can never become a one-way trapdoor — the player always has a path back to the shelf without having to finalize a sheet.

Lifecycle copy follows the same shift end-to-end. The EndBanner CTA used to call `game.reset()` (in-place wipe of the active save); post-F-12 it calls `game.createSave(true)`, which adds a new tome and binds it as active while preserving the closed archive on the shelf. The Inspector splits its old single "Reset / Replace archive" into two distinct lifecycle ops: a non-destructive "Open save library" ghost button and an explicitly destructive "Reset this save" / "Wipe and re-roll this save" with rust-iron border styling. The non-destructive escape hatch is the path the End-Banner and the menu both surface; the in-place wipe is intentionally the visually-louder "this is the dangerous one" path.

Thread continuity now follows the same pattern as Cairn encounter seeding and inventory acquisition: a focused backend-only structured updater runs *after* the deterministic outcome exists but *before* turn checkpointing and narration. It sees the resolved `OracleOutcome`, player input, executed backend steps, current threads, and a bounded thread-oriented memory context; returns a validated bounded batch of `create | update | resolve` ops; and Python applies those ops to canonical `GameState.threads`. This keeps narration prose-only while allowing long-running threads to evolve as canon. Invalid/duplicate ops collapse safely to no-ops rather than blocking the main turn.

The frontend reflects that thread evolution as a *derived* surface only — there are deliberately no edit affordances. `web/src/lib/threads.ts` reads the latest `OracleOutcome.referenced_thread_ids` (with a legacy-singular fallback so older campaigns still highlight) into a bounded "recently touched" set; `ThreadsPanel.svelte` consumes that set to (a) sort just-touched cards to the top of their status group, (b) brighten the left rail to gold, (c) play a one-shot non-looping CSS pulse that respects `prefers-reduced-motion`, and (d) carry an Alagard `advanced` / `just resolved` pip beside the existing status pip. The cue is intentionally layered so it survives reduced motion, screenshots, and non-color displays — no single channel carries the entire signal alone.

NPC continuity now follows the same bounded-updater pattern as threads, but with one extra invariant: recurring people should not vanish from canon just because they leave the active cast. `src/dungeon_master/npc_updater.py` runs after the deterministic outcome exists but before checkpointing/narration, sees the resolved `OracleOutcome`, player input, executed backend steps, current NPC list, and a bounded NPC-oriented memory context, and returns a validated bounded batch of `create | update | retire` ops. Python applies those ops to canonical `GameState.npcs`, and touched ids are merged back onto the outcome via plural `referenced_npc_ids` plus a primary `referenced_npc_id` for compatibility. NPCs are never deleted here; instead, `NPC.status` becomes `active` or `retired`. That keeps recurring-cast continuity available to the memory sidecar and the inspector while still letting the active cast shrink visually. "Promote" is intentionally not a separate op kind — it is just an `update` that changes `role` and/or `disposition`.

One more orchestration seam now sits in front of both continuity updaters: `src/dungeon_master/continuity_classifier.py`. Rather than deterministically keyword-gating continuity work or always paying for both model calls, `GameService` first makes one tiny model request for a single scope token: `none | threads | npcs | both`. The classifier sees only the resolved turn, the current scene, and very small continuity snapshots, and it is instructed to be conservative: if unsure, choose `both`; if the call fails or the output is malformed, the service also falls back to `both`. This preserves the project's rule "use the model for interpretation, not regex heuristics" while still letting obviously local/self-contained turns skip unnecessary continuity-update cost. Crucially, the service still normalizes `referenced_thread_ids` and visible-only `referenced_npc_ids` even when one or both expensive updater calls are skipped, so receipt/navigation invariants do not depend on the classifier deciding to run.

The frontend mirrors that NPC evolution the same way it mirrors threads — as a *derived*, read-only surface. `web/src/lib/npcs.ts` is the structural dual of `web/src/lib/threads.ts`: `recentlyTouchedNpcIds` reads the latest `OracleOutcome.referenced_npc_ids` (with a legacy-singular fallback) into a bounded set, and `sortNpcsForDisplay` orders the cast as `[active, touched] → [active, untouched] → [retired, touched] → [retired, untouched]` with original index preserved within ties so the panel never reshuffles when nothing relevant changed. `NPCsPanel.svelte` consumes that set to (a) sort just-touched cards to the top of their status group, (b) brighten the left rail to gold, (c) play a one-shot non-looping `npc-pulse` animation that respects `prefers-reduced-motion`, and (d) carry an Alagard pip — `advanced` for active changes, `newly retired` for retirements — beside an explicit `retired` status pill. The pulse is deliberately suppressed on already-retired cards: a pulse on a muted card reads as visual noise rather than a signal, and the pip + gold rail already carry the recency cue. Retired NPCs sink with verdigris styling and reduced opacity rather than disappearing, which keeps the panel canonically aligned with what the backend persists. The cue is layered (sort + rail + pulse + pip) for the same reasons threads are: it has to survive reduced motion, screenshots, and non-color displays without any single channel carrying the entire signal alone.

F-16 intentionally changes the meaning of that surface without changing the overall read-only pattern: the NPC panel is **introduced cast only**, not an omniscient GM notebook. Hidden cast records are backend continuity anchors and do not belong in the visible Inspector roster. The backend enforces this by storing hidden NPCs in `hidden_npcs`, not by expecting the frontend to remember to filter them out. One more safety net lives in `GameService`: after narration commits, a deterministic exact-name reveal pass moves any hidden NPC explicitly named in committed prose into the visible roster and merges the id onto `OracleOutcome.referenced_npc_ids`. That way, even if the updater kept a figure hidden while narration surfaced them, the saved state still matches what the player actually saw.

H-01 extends that same pattern from **who is visible** to **what the player is allowed to call them**. `NPC` now carries both a canonical backend `name` and a safe player-facing `player_label` plus `player_label_kind` (`proper_name` or `descriptor`). Player-facing prompt, memory, and audit paths render `npc.display_label()` rather than canonical `npc.name`, so a recurring figure can be visible as "the ash-veiled bellringer" before the fiction grants "The Hierophant." Promotion is deterministic and one-record-only: if committed narration later grants the true name, `GameService` upgrades the existing visible NPC from descriptor to proper-name label instead of minting a second record. The same safety rule also informs H-02's receipt-link substrate: `OracleOutcome.referenced_npc_ids` is now filtered down to the visible roster before persistence, so frontend receipt pills can treat that field as player-safe navigation data rather than a mixed visible/hidden continuity bag.

The frontend mirrors that safety model explicitly instead of trusting ad-hoc component reads. `web/src/lib/types.ts` now carries `player_label` + `player_label_kind`, `web/src/lib/npcs.ts` centralizes `npcDisplayLabel()` / `npcKnownByDescriptor()` plus safe outcome→visible-NPC lookup, and `NPCsPanel.svelte` renders descriptor-visible figures with a `known by sign` cue so the roster never implies canonical-name knowledge it does not have. H-02 uses the same "one-shot store signal" pattern as transcript jumps rather than inventing a second inspector state machine: `GameStore.requestInspectorFocus(section, entityId)` opens the drawer, `Drawer.svelte` accepts a `reopenToken` nudge, the threads/NPC panels consume a `focusSeq` to scroll/highlight the targeted card, and `MechanicalReceipt.svelte` renders compact continuity pills (threads / visible figures) that route through that signal. The result is a layered navigation cue: receipts show *what* changed, the inspector opens to *where* it lives, and the targeted card itself flashes once so the player's eye lands on the right continuity object.

One more pattern now exists around manual/browser verification: continuity-specific UI branches get their own **isolated fixture save library**, not one-off mutations to the live campaign. `src/dungeon_master/fixture_cli.py` seeds canned saves into a separate save-library root (defaulting to the OS temp dir so the repo's real `data/` tree is never the target by accident), reusing the exact canonical `SaveLibrary` / `StateStore` on-disk shape rather than inventing a fake import format. The fixture states deliberately opt into the current roster contract (`npc_roster_version=2`) so load-time legacy repair does not rewrite them, and the frontend consumes them through the normal shelf/bootstrap path. A small dev-only Vite seam (`VITE_API_PROXY_TARGET`) complements that pattern: browser/manual smoke can point a second frontend dev server at a second backend without editing checked-in proxy config or touching the real campaign backend bound to `:8000`.

The Vrtanes follow-up clarified a second pattern around migrations: **one-time save upgrades should have an explicit backend tool, not only an implicit load-time side effect.** Load-time repair remains useful for lightweight invariants (`npc_roster_version` split, terminal-state sync), but when the goal is "audit this specific old campaign against newer core features without reseeding it," the right surface is a dry-run/apply command with a human-readable report. That pattern now exists as `GameService.backfill_current_save(...)` plus the `dungeon-master-backfill` CLI. The command deliberately reuses the same canonical repair steps the live app already trusts (Cairn character backfill when needed, legacy NPC roster split repair, terminal-state sync, forced `memory.json` rebuild) but makes them explicit, targetable to a save slot, and reviewable before writing. One more guardrail is baked into the audit report: visible NPC names are scanned against the committed transcript/current scene, and any name that lacks explicit textual support is reported as suspicious rather than silently canonized. That keeps the maintenance path aligned with the clarified rule "backend-hidden true names are not player knowledge until the fiction directly grants them."

Enemy-first combat now follows the same philosophy: the backend introduces only the minimum canonical metadata necessary to express the new behavior, then lets the existing UI/rendering surfaces read it indirectly from committed state. `EncounterState` now carries `initiator: player | enemy`, mirrored onto `CairnResolution.combat_initiator` so receipts/tests/narration can tell who seized the opening blow. `src/dungeon_master/cairn.py` adds a dedicated `resolve_enemy_opener(...)` path rather than teaching generic `suffer_harm()` to start fights. That distinction is load-bearing: a trap, cave-in, or curse may hurt the player without implying an encounter, while an ambushing ghoul should both harm the player **and** seed canonical combat state. The enemy-opener path therefore reuses `_ensure_encounter()` / `_seed_encounter()` with an explicit initiator, applies deterministic harm immediately via `_resolve_enemy_turn(preferred_attacker_name=...)`, clears the first-round DEX gate, and advances the encounter to round 2 so the player's next turn lands inside the already-existing combat loop. This avoids inventing a fragile half-round state machine while keeping retreat, morale, memory open-loops, and the player-attack flow aligned with the same encounter model.

The planner/service seam for that behavior is intentionally asymmetric. `TurnRouter` grows an **internal-only** `enemy_opener` op kind, but the legacy public route remains `harm`. That lets the backend distinguish "hostile opener that should seed combat" from "generic damage that should not" without forcing a new frontend-visible route/outcome enum through the store, receipts, or stream envelope. `GameService._execute_turn_plan(...)` is the only place that knows the difference: `enemy_opener` dispatches to `resolve_enemy_opener(...)`, while ordinary `harm` still dispatches to `suffer_harm()`. The result is a conservative contract outward and a richer distinction inward — exactly the pattern the project now uses for several other features (planner ops more expressive than the legacy route summary, plural thread/NPC linkage richer than the old singular compatibility fields, etc.). Because broad "find/start a fight" intent can be over-eagerly interpreted by the planner model, any generated `attack`, `enemy_opener`, or `harm` plan now receives a second structured combat-mechanics review. That review is also LLM-backed and Pydantic-validated rather than regex-based: it inspects the original player text plus the proposed typed plan and must explicitly approve immediate mechanics. Review failure or denial degrades the turn to narration/scene setup, preserving the player's intent without spending their action or applying damage.

F-19 adds a backend-only Cairn encounter-scaling policy before generated foes become canonical. Encounter seeding can still be LLM-authored and on-the-fly, but Python now normalizes that output through typed threat levels (`ordinary`, `hardier`, `serious`) plus the campaign `danger_profile`. The default invariant is Cairn-shaped: ordinary foes cap around 3 HP, hardier foes around 6 HP, serious threats may reach 10+ HP only when telegraphed, with armor similarly clamped by threat band. Fallback encounters are no longer fixed 6 HP sponges; they default to an ordinary 3 HP foe.

F-18 adds a typed fiction-first setup lane rather than a hit-location subsystem. `TurnRouter` can emit `setup_advantage` with a bounded payoff (`enhanced_attack`, direct STR damage, skipped DEX gate, denied enemy action, impaired/exposed foe, forced morale), `GameService` dispatches it to `CairnEngine.setup_advantage(...)`, and `EncounterState.pending_advantages` stores the earned opening until a matching attack consumes it. This keeps Fear & Hunger-style "learn/exploit the foe" inspiration inside Cairn levers instead of adding limb HP or universal called-shot buttons.

F-15 backend v1 adds a persistent `CampaignSeed` on `GameState`. The seed separates tone/genre/era/magic/stakes from `danger_profile`, exposes `POST /api/state/campaign-seed` before campaign start, threads seed guidance into character-template and campaign-generation prompts, and lets encounter scaling read `state.campaign_seed.danger_profile`. Save summaries now include preset + danger profile, and the OOC explainer sees seed plus enemy threat/weakness/advantage context.

Campaign generation now treats small bounded-list overruns as normalizable structured-output noise, not as a reason to commit a placeholder campaign. The model may still brainstorm too many threads/NPCs despite prompt limits; `GeneratedCampaignWorld` therefore accepts the product-shaped bounds (`threads` 1-3, `npcs` 0-3) and trims overflow in a `mode="before"` validator before Pydantic validates the rest of the payload. This is intentionally narrow: wrong types, missing required scene/setting/oracle tables, malformed JSON, or invalid oracle tables still fail and go through the existing fallback path. The important invariant is that harmless over-production should not turn a valid opening into `_configuration_required_state(...)`, because that placeholder state is player-visible and gets persisted as an active campaign.

The frontend pass for F-15 / F-18 / F-19 follows the project's existing "labels live next to types, mutations live in the store, surfaces stay read-only by default" pattern. `web/src/lib/types.ts` mirrors `CampaignSeed`, `EncounterThreatLevel`, `EncounterAdvantagePayoff`, and `PendingEncounterAdvantage`; `web/src/lib/campaign-seed.ts` is the single source of truth for label/blurb dictionaries, curated presets, `defaultCampaignSeed()`, `seedsEqual(a, b)`, and `seedBadgeLabel(seed)`. The store gains `updateCampaignSeed(seed)` routed through the standard `#run` plumbing so 409 conflicts surface the same way every other state mutation does. The only **editable** F-15 surface is `CampaignSeedEditor.svelte` mounted above the character-creation mode picker; once the campaign reaches `active` or `ended` the editor renders a locked summary header instead of inputs, matching the rule that seed is locked at campaign start. F-18 / F-19 are deliberately **read-only** on the frontend: `CombatTracker.svelte` surfaces threat-tier pips, weakness/tactics lines, and pinned vs loose `pending_advantages`; `MechanicalReceipt.svelte` shows the F-18 setup/payoff/consumed chip on every Cairn-flavored receipt; the `Inspector` adds a "Campaign setting" drawer that always renders the seed read-only. The combat adapter (`combat.ts`) defaults missing `threat_level` to `ordinary` and missing `weakness`/`tactics` to `""` so legacy save state still loads cleanly.

The planner now has a second safety stop for ambiguous actor/target references: an internal `clarify` op. This is intentionally backend-only and does not create an oracle outcome. When the model cannot safely resolve who a pronoun or first-person-plural reference points to, and that choice would affect who is helped, harmed, moved, rescued, commanded, or committed to danger, the typed plan can return `player_action` + `clarify`. `GameService` then persists the player's message and a `Clarification needed` narrative event with the question, but skips deterministic mechanics, oracle history, continuity updates, and narration. Streaming turns follow the same contract: planning completes, mechanics are marked skipped, and the clarification message is committed as the visible response. This keeps the "ask instead of guessing" behavior in the same typed planner/service seam as other natural-language interpretation, without adding UI buttons or regex pronoun heuristics.

Cairn weapon resolution now treats dangling primary-weapon state as corrupt state, not as a license to improvise. If an actor has `primary_weapon_item_id` but that item is absent from inventory, `resolve_attack(...)` raises instead of silently falling back to `Unarmed strike`. The live bug that motivated this was a rollback target where Vrtanes' `primary_weapon_item_id` survived but the `Notched iron cudgel` inventory item did not; silent fallback made the receipt look like an intentional bare-handed attack. The invariant is now fail-loud: explicit unarmed attacks are still possible only when no primary weapon is tracked or the caller deliberately names no weapon on a sheet without a primary.

Coordinated party attacks are represented as one `attack` outcome with richer Cairn receipt data, not as two separate turns and not as narrator-only color. The planner can emit an internal `coordinated_attack` op when the player clearly orders the protagonist and one or more named party members into the same immediate offensive tactic. `GameService` resolves those actor labels into `AttackActor` records, and `CairnEngine.resolve_coordinated_attack(...)` runs one shared opening DEX gate for the side, using the lowest participant DEX as the conservative coordination bottleneck. If the side acts, each participant rolls weapon damage against the same target in order and the receipt stores a `CoordinatedAttackParticipant` row for each actor; if the opening gate fails, those participant rows still record that the strike did not land. The public outcome kind stays `attack`, so frontend/state routing remains stable while `CairnResolution.coordinated_attack` + `coordinated_participants` let the receipt tell the truth.

The frontend ambush/coordinated-combat surface is the dual of that conservatism: the public `OracleKind` stays `harm` for ambushes and `attack` for coordinated strikes, while richer optional fields on `CairnResolution` drive presentation. `web/src/lib/combat.ts` carries `EncounterState.initiator` through the adapter and exposes `enemyInitiated(state)` so every UI surface uses the same predicate; `web/src/lib/cairn.ts` exposes `isAmbushOpener(outcome)` (`combat_started === true && combat_initiator === 'enemy'`) and `formatCombatInitiator(...)` for receipt-side display. The initiator label intentionally says `Player opened the fight`, not `Player struck first`, because a player-opened round can still fail its DEX gate. Ambush cues are layered across the `Combat` badge, `CombatTracker`, `MechanicalReceipt`, and `formatHarmHeadline(...)`. Coordinated attacks reuse the existing receipt body with one compact `Coordination` row: each chip shows actor, weapon, and damage/no-strike from backend participant data. Crucially, none of this required a new frontend-visible outcome kind, so the existing receipt switch / store / type unions remain stable.

Campaign endings now follow the same broader project philosophy: **minimal canonical state change first, richer UI/archive behavior later**. Rather than building a bespoke archive/save object up front, the backend extends `GameState` itself with a single terminal status (`CampaignStatus.ENDED`) plus a separate semantic reason (`CampaignEndReason.DEATH | RETIREMENT | VICTORY`) and lightweight metadata (`campaign_ended_at`, `campaign_end_summary`). That mirrors how F-05 treated ambushes: keep the public/state contract conservative but sufficient, then let later surfaces decide how to render it. The service layer owns the transition. Explicit retirement/victory run through one deterministic `end_campaign(...)` helper; automatic death is detected inside the ordinary turn-commit path after the deterministic outcome already exists. The turn still gets its normal narrative/checkpoint, but the state is marked terminal *before* narration is generated so the final prose can see the ended status and the persisted turn checkpoint already reflects terminal canon. A terminal `Campaign ended` system event is appended after the narrative event, preserving the sequence “player -> oracle/mechanics -> final narration -> terminal audit event.” Existing mutating endpoints do not each learn custom end-state logic; they all inherit it from `_ensure_active(...)`, which now emits a reason-aware conflict once the run is ended. The future save-selection/archive system can therefore stay orthogonal: each save simply carries its own `active` vs `ended` lifecycle instead of requiring a migration away from a one-off archive schema.

Terminal narration now has an explicit backend prompt exception. When `GameState.campaign_status == ended`, `NarrativeEngine` appends terminal-closure instructions and swaps the per-request output instruction from "end with one concrete prompt for action" to "do not end with a next-action prompt, menu, or new-character suggestion." The UI/archive layer owns new-run calls to action; the narrator's job on the fatal turn is only to close the final beat grounded in the already-marked terminal state.

The frontend pass for campaign endings extends that same minimal-canon-rich-rendering pattern into the Svelte client. `web/src/lib/types.ts` mirrors the new union and metadata fields directly without inventing a separate "archived state" record, and `web/src/lib/end-campaign.ts` carries the pure presentation helpers (`isCampaignEnded`, `endKicker`, `endHeadline`, `endSummary`, `formatEndedAt`) so per-reason copy and timestamp formatting are testable without DOM and decoupled from any one component. `web/src/App.svelte` collapses its play-time conditional into an exhaustive `loading | setup | active | ended` switch — instead of inlining "is play allowed?" booleans across three template branches, the layout is a single classification + a per-mode tree, which makes adding future modes (e.g. `paused`, `frozen`) a one-line edit. The ended branch keeps `StatusStrip`, `CharacterFolio`, `ChatFeed`, and `Inspector` mounted (the chat is preserved as a read-only archive) but **replaces the Composer wholesale** with `EndBanner.svelte`. We deliberately replace rather than disable: a frozen composer would invite the player's "click input → type" muscle memory into a control that does nothing, while a missing input box makes the lifecycle shift structurally obvious. The new `/retire` and `/victory` slash commands likewise bypass the planner — they are state transitions, not in-fiction actions, so they hit `/api/campaign/end` directly through `game.endCampaign(...)` and avoid an unnecessary multi-minute model round-trip. The Inspector goes read-only by status (chaos commit disabled, notes shown as static prose, reset rephrased as "Replace archive"), surfacing the disabled state at the source rather than letting the player twiddle controls that would 409 on the backend's `_ensure_active` guard. The cue is layered (banner replacement + read-only inspector + desaturated `app__main--ended` surface + per-reason kicker color) for the same reduced-motion / screenshot / no-color robustness as F-03/F-04/F-05.

## Mechanics Scope

The project started oracle-first: deterministic scene pacing, threads, NPCs, and consequence prompts with a fiction-only character sheet. The user has now clarified that this was **not** a final rejection of structured RPG mechanics; they want the experience grounded in rules and have chosen a **Cairn 2e-inspired dark-fantasy adaptation** as the next layer.

That means the mechanics scope is now:

- keep the existing deterministic oracle for yes/no resolution, scene checks, random events, chaos, and campaign pressure
- add a lightweight but real character rules layer: Cairn-flavored stats, HP, inventory burden/slots, armor/weapon tags, and deterministic item effects
- add a typed survival/time layer inside that same Cairn state: watch-based day/night progression, meal/sleep pressure, ration consumption, and deprivation that blocks recovery until addressed
- automatically backfill those mechanics from the already-authored character sheet and generated opening state so the user does not have to redo character creation
- keep the LLM out of canonical math, roll resolution, item modifiers, and state mutation
- in the current backend implementation, the above is realized as a separate `CairnEngine` (`src/dungeon_master/cairn.py`) that sits beside `OracleEngine`, not inside it
- Cairn item powers are now typed, item-bound mechanics rather than a generic buff system. `CairnItemState.power` can mark an item as a spellbook, scroll, relic, or holy relic with a bounded effect vocabulary (`restore_attribute`, `clear_condition`, `enhance_attack`, `reveal_sign`, `ward_or_pacify`, etc.), optional charges/uses, recharge text, spellbook Fatigue, and WIL-save risk under danger/deprivation. This keeps prayer/intercession close to Cairn 2e's item/relic philosophy: a plain prayer remains fiction/oracle/save territory, while a carried holy icon can matter mechanically only through its typed holy-relic effect.

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

B-02 adds a separate **campaign directives** steering layer to the backend prompt architecture. `setting_notes` / `player_notes` remain canonical campaign/backstory prose, but `GameState.directives` (`world_guidance`, `play_guidance`) is a durable OOC instruction block that is fed into narrator/Cairn/updater/explainer prompts when present. The service deliberately persists directives without appending a visible `action_log` event: they are save-scoped prompt steering, not in-fiction transcript events. This keeps the future frontend free to present directives as a tucked-away advanced control rather than as ordinary chat history.

The narrator and turn planner now also receive a bounded **memory context** assembled from `data/memory.json`, not from the raw transcript. The key design choice is that this memory layer avoids ad-hoc lexical heuristics for meaning extraction. Instead, it leans on:

- canonical references already present in state/outcomes (`referenced_thread_id`, `referenced_npc_id`, current scene, active encounter)
- plural touched-thread linkage on outcomes (`referenced_thread_ids`) when a turn advances more than one thread
- recency / active-status ordering
- compacted sidecar cards rather than replaying full `action_log` / `oracle_history`

This preserves separation of concerns: memory compaction/retrieval is an application layer, not an invitation for the narrator to treat past prose as canon.

The newer scene-transcript pass narrows that statement further: the app still avoids replaying the **full campaign** transcript, but it now deliberately replays the **full current-scene** transcript because that is the shortest horizon where conversational continuity failures were actually happening. Past scenes stay compacted; the live scene stays raw.

The first memory pass rebuilt `data/memory.json` from a lossy replay of `GameState` alone. That has now been corrected: `GameService` reconstructs committed turns from canonical outcomes plus exact turn-checkpoint metadata (`player_input`, `execution_context`) before rebuilding the sidecar. This matters because explicit oracle routes (`/ask`, `/event`, `/scene`) do not always emit a player event into `action_log`, and planner-executed deterministic prep steps would otherwise vanish from derived memory.

The current implementation uses LiteLLM for model routing. The default model is OpenRouter Kimi K2.6 via `openrouter/moonshotai/kimi-k2.6`, with task-based reasoning: medium for ordinary player-action and yes/no narration, high for scene checks and random-event synthesis. Reasoning tokens are excluded from the response. When no usable API key/model configuration is present, the app returns deterministic placeholder narration so the oracle loop remains playable.

One more configuration pattern now sits underneath that client layer: **global runtime config and per-task model profiles are separate objects on purpose**. `src/dungeon_master/config/app.py` now defines:

- `AppConfig` for cross-cutting runtime paths/settings
- `LLMConfig` for provider/runtime defaults (model, key, base URL, timeout, retries, reasoning visibility)
- `LLMProfiles` for the actual per-subsystem completion budgets

This is deliberately not "one env var per call site." The user wanted reasoning/temperature/token choices to be easy to trace, but not flattened into a fake single knob. The resulting rule is: env controls the narrator-facing defaults and runtime envelope, while task-specific planner/updater/generator behavior lives in typed Python profiles. That fixes the previous smell where `LITELLM_MAX_TOKENS` looked like a global ceiling but was secretly being used as a floor inside unrelated structured-generation paths.

Streaming pattern:

- `src/dungeon_master/narrative.py` exposes both buffered generation (`generate_result`) and generator-based streaming (`iter_stream`) using a shared `CompletionDelta` / `NarrativeResult` contract.
- `src/dungeon_master/campaign.py` now mirrors that pattern for non-play setup flows. Character templates, quiz generation, draft generation, quizzed draft generation, and campaign world generation each have both buffered `*_result` entry points and `iter_*` generator entry points, so setup no longer needs a separate bespoke transport.
- `src/dungeon_master/service.py` lifts those into app-level result + stream methods and persists thinking where canon exists. If the stream resolves to a `GameState`, the final thinking is attached to a persisted `GameEvent`; if the stream resolves to a setup artifact (templates / quiz / draft), the final thinking is returned in the terminal API payload because there is no canonical active campaign state yet.
- `src/dungeon_master/api.py` standardizes the wire format as **NDJSON** (`Content-Type: application/x-ndjson`, one JSON object per `\n`). The lifecycle is `meta` → `thinking_delta*` → `content_delta*` → exactly one terminal `final_state` / `final_payload` / `error`. SSE was rejected because every streamed endpoint is a POST with a JSON body (EventSource is GET-only) and the frontend was already going to need a custom `fetch` + `ReadableStream` parser; NDJSON is simpler than SSE once you're parsing manually anyway.
- The frontend speaks the same NDJSON contract via `web/src/lib/streaming.ts` (`consumeStream`) + `web/src/lib/streaming-types.ts` (the discriminated `StreamEvent` union). The store branches on the typed `StreamResult` (`final` / `aborted` / `error`) without reasoning about partial-state HTTP failures. The setup-stream path now also treats server-aborted streams as explicit user-visible errors rather than silently returning `null`.
- The OOC explainer follows the **setup-artifact** side of that streaming contract rather than the state-mutating side. `src/dungeon_master/explainer.py` owns a dedicated prompt/client separate from `narrative.py`; `GameService.explain(...)` / `stream_explain(...)` load state through a read-only helper, derive bounded continuity context from `memory.json` in memory only, and return `ExplanationResult` objects instead of `GameState`. The HTTP layer exposes those as `/api/explain` and `/api/explain/stream`, with the stream terminating as `final_payload(kind="explanation")`. That separation is load-bearing: rules explanations may reference canon, latest receipts, and current encounters, but they must never themselves become canon.
- On the frontend the OOC explainer surfaces as an **ephemeral chat-only** affordance, deliberately *not* as a separate panel. The chat is the player's existing forward channel, so dropping the OOC card into the same scroll keeps cognitive load low; making it ephemeral (a `ClientNote` of kind `"explanation"`, not an `action_log` entry) is what enforces the no-canon contract on the client side. The card is rendered with a distinct `OOC · Archivist` speaker variant + verdigris rail + optional `Q:` row so the player can tell at a glance that the bubble is non-canonical, without us having to invent a separate surface. Slash dispatch routes `/explain` directly to a dedicated `game.explain()` method instead of through the planner so there is no path by which the exchange can leak into canon — even if the planner's prompts are later revised, OOC stays out of the loop.
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
- **`Composer.svelte`** (sticky bottom): textarea with rotating slash-command placeholder, Cmd/Ctrl+Enter to send, parses input via `lib/slash.ts`. Above the send-row sits the F-07 **common-actions tray** (`lib/common-actions.ts`) — a small horizontal strip of pixel pills (`Ask oracle`, `Random event`, `Scene check`, `Check gear` always; `Attack`, `Recover`, `Retreat` only during an active encounter). Click prefills the textarea (no auto-submit, by user-explicit choice over both auto-fire and a hybrid); typed prose is preserved by appending the prefill on a fresh line so the player can see and undo. Pills are `disabled` while `game.isLoading` and the toolbar carries `aria-disabled` for screen-reader lockout. The tray is structurally absent on setup / ended layouts because the Composer itself is unmounted there. Keeping the visibility and replacement rules in a pure helper (`deriveCommonActions` / `applyCommonAction`) makes them unit-testable without DOM and keeps the tray in lock-step with `slash.ts` parser entries.
- **`Inspector.svelte`** (slide-in right drawer, default closed): compact chaos control row, collapsed threads, NPCs, notes editor, transcript search, full oracle history (with text + kind filters), reset campaign button. All sections are collapsed by default to prevent the unusable nested-scroll/tall-dashboard behavior the user rejected. The inspector is structured as a 3-row flex column — `<header>` / `<div class="body">` (the only scrollable region, with `overflow-y: auto` and `scrollbar-gutter: stable`) / `<footer class="end">` — so the lifecycle buttons sit beneath the scroll surface as a fixed band rather than sticky-overlaying the bottom drawer. Drawer sections (`web/src/components/Drawer.svelte`) pin `flex-shrink: 0` so they keep their flap's intrinsic `min-height: 3.55rem` even when seven of them stack inside a short viewport — without this, the parent flex column would silently squash flap labels and chevrons under each other. Drawer bodies and the inspector body both reserve `scrollbar-gutter: stable` and apply `overflow-wrap: anywhere` as a defensive horizontal-overflow fallback. Long prose (NPC dispositions, thread stakes, setting/player notes preview, Cairn build notes) wraps freely without `-webkit-line-clamp` because the drawer's internal scroll is the right escape hatch when content is genuinely long; the previous clamps silently dropped the back of every long string and forced the player to hover for a `title`-tooltip just to read past the cap.

F-09 history browsing extends the chat surface and the inspector through a single shared pure helper module `web/src/lib/history.ts` (transcript-row derivation, token-AND search across rows + outcome summaries, oracle-to-narrative-event linking, oracle filter by free-text + `OracleKind` whitelist) plus a small store-level navigation signal. The browsing pattern reuses the **chat is forward-only, inspector is reference** split: search and filter UI lives in the inspector (Transcript Drawer + filter strip on Oracle history), but the *result* of a click is to teleport the chat surface to the matching anchor and apply a 1.7 s gold flash, leaving the inspector to close itself. The store's `scrollRequest: { eventId, seq } | null` carries the navigation command — the seq counter rotates on every call so back-to-back same-eventId requests still re-trigger the feed's scroll/flash effect. ChatFeed gates auto-follow on a 120 px bottom band (with a floating "Jump to latest" pill when off-band) and uses *instant* scroll for token-driven follow so a smooth-scroll mid-animation can't trip the threshold and stall the follow on the next streamed token; smooth scroll is reserved for explicit jumps. Anchor IDs match `ChatFeed`'s rendered ids exactly (including the synthesized `opening_<state-id>` for the first DM beat) so search results land on the same DOM nodes the chat already mounts. Helper-pure derivations (`deriveTranscriptRows`, `searchTranscript`, `findNarrativeEventForOracle`, `filterOracleHistory`) keep all the dedup / matching rules unit-testable without DOM and ensure the search and chat surfaces can never disagree about what the transcript "is".

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
- `GameState.party_members` is the companion/hireling harness. Each `PartyMember` wraps a normal `CharacterSheet` and optionally links back to a source `NPC`, so companion stats, inventory, item powers, and burden use the same schema as the protagonist instead of a parallel "NPC stats" model. Actor-specific receipts use optional `CairnResolution.actor_id` / `actor_name` fields.
- `GameState.campaign_status` gates the whole app shell: `character_creation` -> `ready_to_start` -> `active`.
- `CharacterGenerator` produces archetypal templates and scratch drafts before campaign generation exists.
- `CampaignGenerator` now accepts a finalized `CharacterSheet` and builds the world around it rather than inventing the player premise itself.
- `InventoryItem` now also carries a nested `cairn` item profile (slots, tags, weapon die, armor bonus, uses, equipped), allowing the backend to preserve the authored item prose while still treating gear mechanically.
- Active-play inventory progression now follows the same pattern as backfill and encounter seeding: the planner may emit an `acquire_item` op from free text, but the actual item list is authored into a validated JSON shape by a focused Cairn prompt and then committed in Python as real `InventoryItem` objects. This keeps the player's main interaction free-text-first while still preventing narration from silently granting untracked loot.
- The new survival/time layer follows the same backend-first pattern. The planner does **not** author clocks or deprivation prose directly; it returns typed `time_advance` plus explicit survival actions (`eat`, `sleep`) at the plan level, and Python owns the actual watch/day-night advancement, ration-bundle consumption, threshold math, and aggregate `deprived` synchronization. This preserves the project rule "use the model for interpretation, not for canonical bookkeeping" while avoiding brittle regexes like scanning the turn text for `sleep` or `ration`.
- Active-play party inventory transfer is deterministic: the planner emits `transfer_item` with typed actor names and item name, then `GameService` resolves actor labels against the player plus active party members, moves the existing `InventoryItem` object, clears equipped state on transfer, and recomputes both sheets' burden. Recruitment follows the same typed boundary: `recruit_npc` names a visible NPC, the service creates a linked party member, and the Cairn engine backfills the companion sheet through structured output when a model is configured. The recruitment path now includes recent player-visible transcript snippets for that recruit in the authored companion context, and Cairn backfill treats concrete carried/wielded gear already surfaced in play as structured inventory to preserve unless canon says it was lost, traded, or discarded.
- Linked party members are denormalized character sheets, not a second source of identity truth. When a visible source NPC later promotes from descriptor to proper-name label (or has role/disposition updated), `GameService` resyncs the active `PartyMember` sheet name/archetype/epithet and loyalty from that visible NPC during disclosure, load, and explicit save backfill. The folio then renders the party sheet while suppressing a separate party note if it duplicates the sheet's own subtitle/body text.
- Legacy saves without `character` are accepted. `GameState` seeds a conservative sheet from `player_notes` so old campaigns remain playable and the left folio never crashes.
- One-time current-character migration pattern: if a live campaign or campaign start sees `character.cairn.source == "unset"`, `CairnEngine.ensure_character_state(..., allow_backfill=True)` asks the LLM for a structured Cairn backfill: stats, skills/abilities (textual specialties, not D&D modifiers), and a practical starting bundle. Biography mostly influences stats, condition, skills, abilities, and notes; inventory is intentionally kept less on-the-nose, with at most one or two biography-derived signature items. The migrated state is then persisted with `source == "narrative_backfill"`.
- `TurnRouter` now uses LLM-backed structured classification instead of regex routing. More complex Cairn interactions (attacks, incoming harm, recovery, equipment toggles) are exposed as explicit FastAPI operations so the frontend pass can choose deliberate controls rather than over-aggressive NLP inference.
- The newer combat pass also widened the router's responsibility boundary without overloading the rules engine: the router may classify intent into `attack`, `harm`, `recovery`, or `equip`, but `CairnEngine` still owns all canonical combat math and enemy-state mutation. Separation of concerns remains router -> service orchestration -> deterministic engine.
- Frontend rendering of Cairn state lives in a small dedicated module:
  - `web/src/lib/cairn.ts` — pure formatting helpers (defaults, render gating, burden tier, status priority, ability / stance / rest-kind labels, item tag labels, and the receipt headline switch). No inference, no mutation. Exhaustive Vitest coverage in `cairn.test.ts`.
  - `web/src/components/CairnReadout.svelte` — read-only stat / burden / statuses / skills / abilities / (optional) build-notes block. Surface-agnostic so it can sit inside the folio's iron rail and above the editor's parchment surface.
- `CharacterFolio.svelte` hosts the readout for active play and now renders the player plus active `GameState.party_members` as switchable folio tabs. Each tab uses the same `CharacterSheet` rendering path, so companion HP/STR/DEX/WIL, burden, item powers, equipped badges, and inventory tags never fork into a parallel NPC-card UI.
- `MechanicalReceipt.svelte` is exhaustive over `OracleKind` (TS will fail at build time when a new kind is added without a branch) and surfaces structured Cairn fields in the body when `outcome.cairn` is populated, including optional `actor_name` attribution for companion-driven mechanics.
  - `Inspector.svelte` adds a collapsed "Cairn build notes" drawer that is hidden when the character is unset or has no notes.
  - `CharacterEditor.svelte` shows the read-only Cairn block above the editor only when the draft is already backfilled (`character.cairn.source !== "unset"`).
- The frontend Cairn/party pass is intentionally **read-only**. Companion recruitment, item transfer, named-actor attacks/saves/harm/recovery, and inventory changes still flow through the existing chat-first `/api/turn` planner; the folio tabs are an evidence surface, not a second control panel.

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
