# Feature Kanban

## Working Rules

- **Primary interaction model stays chat-first + LLM-inferred.** Explicit controls/commands are optional affordances and discoverability aids, not the main gameplay mechanism.
- **Threads and NPCs should update dynamically through the game system / LLM workflow.** They are **not** intended to become user-editable admin forms.
- **Save slots and rollback exist as real future features, but are not near-term priorities.**
- **We should work ticket-by-ticket in plan mode** rather than trying to ship the whole backlog in one pass.

## Ready Next

### F-01 Retreat / Disengage
- Status: `done`
- Priority: `high`
- Goal: Add a canonical retreat / disengage action so combat has a real exit path.
- Why:
  Combat now has attack/harm/recover/equip *and* a canonical flee/withdraw mechanic that runs through the same chat pipeline.
- Final state:
  - Backend: routed `retreat` action, deterministic resolution in `cairn.py` with DEX save + pursuit roll, explicit `/api/cairn/retreat` endpoint, pursuit/disengage/escape outcomes, and tests across `test_cairn.py`, `test_service.py`, `test_api.py`, `test_turn_router.py`.
  - Frontend: `/retreat` slash command (with `/flee` and `/disengage` aliases) translates to a free-text turn through the existing planner pipeline so narration, memory, and receipts all run uniformly. Composer surfaces a slash suggestion menu (Up/Down + Tab/Enter completion, Esc dismiss). CombatTracker carries a read-only retreat hint when an encounter is active. Tests cover parser, suggestion filtering, and store dispatch (`web/src/lib/slash.test.ts`, `web/src/lib/store.test.ts`).
- Decisions:
  - We deliberately funnel `/retreat` through `submit_turn` rather than the explicit `/api/cairn/retreat` endpoint. The bare deterministic endpoint exists for completeness, but the chat-first invariant says every player turn should produce narration + memory; the planner already classifies "I retreat" → RETREAT, so the slash command and natural language take the same path.
  - The CombatTracker stays a read-only trust surface — no retreat button — but it surfaces a single italicized `/retreat` hint so the affordance is discoverable in context without dragging the player into `/help`.

### F-02 Inventory Progression
- Status: `ready`
- Priority: `high`
- Goal: Let the game canonically add loot / found items / purchases / transfers during active play.
- Why:
  Existing inventory can be used, dropped, and equipped, but active-play acquisition is still a hole.
- Constraints:
  The LLM should ideally be able to drive this through structured interpretation; explicit commands can exist as backup/discoverability.
- Likely touch points:
  - `src/dungeon_master/turn_router.py`
  - `src/dungeon_master/service.py`
  - `src/dungeon_master/cairn.py`
  - `src/dungeon_master/models.py`
  - `src/dungeon_master/api.py`
  - `web/src/components/CharacterFolio.svelte`
  - `web/src/lib/slash.ts`

### F-03 Dynamic Thread Updates
- Status: `ready`
- Priority: `high`
- Goal: Threads should be canonically created/updated/resolved by the game loop, not remain read-only references.
- Why:
  Long-running solo play needs thread state to evolve continuously.
- Constraint:
  User-facing manual editing is **not** the preferred solution.
- Likely touch points:
  - `src/dungeon_master/models.py`
  - `src/dungeon_master/service.py`
  - `src/dungeon_master/narrative.py`
  - `src/dungeon_master/memory.py`
  - `web/src/components/ThreadsPanel.svelte`
  - `web/src/components/Inspector.svelte`

### F-04 Dynamic NPC Updates
- Status: `ready`
- Priority: `high`
- Goal: NPCs should be canonically created/updated/promoted/retired by the game loop rather than staying static opener artifacts.
- Why:
  Recurring cast continuity is central to long-running play.
- Constraint:
  User-facing manual editing is **not** the preferred solution.
- Likely touch points:
  - `src/dungeon_master/models.py`
  - `src/dungeon_master/service.py`
  - `src/dungeon_master/narrative.py`
  - `src/dungeon_master/memory.py`
  - `web/src/components/NPCsPanel.svelte`
  - `web/src/components/Inspector.svelte`

### F-05 Enemy-First / Ambush Combat
- Status: `ready`
- Priority: `high`
- Goal: Support enemy-initiated combat as a fully tracked encounter, not just a harm resolution.
- Why:
  Ambushes and foe-first turns should seed/advance encounter state just as cleanly as player-initiated attacks.
- Likely touch points:
  - `src/dungeon_master/cairn.py`
  - `src/dungeon_master/turn_router.py`
  - `src/dungeon_master/service.py`
  - `src/dungeon_master/api.py`
  - `web/src/components/CombatTracker.svelte`

## Backlog

### F-06 Campaign End / Death / Retirement Flow
- Status: `backlog`
- Priority: `high`
- Goal: Add terminal/late-campaign flow so runs can meaningfully end rather than only being reset.
- Why:
  The user wants a long-running game, but one that eventually reaches endgame.
- Likely touch points:
  - `src/dungeon_master/models.py`
  - `src/dungeon_master/service.py`
  - `src/dungeon_master/api.py`
  - `web/src/App.svelte`
  - `web/src/components/Inspector.svelte`

### F-07 Common Actions Tray
- Status: `backlog`
- Priority: `medium`
- Goal: Add clickable common actions in the UI for discoverability and speed.
- Why:
  Chat-first remains primary, but a tray for common verbs would help usability.
- Candidate actions:
  - `Ask oracle`
  - `Random event`
  - `Scene check`
  - `Attack`
  - `Recover`
  - `Retreat`
  - `Check gear`
- Likely touch points:
  - `web/src/components/Composer.svelte`
  - `web/src/lib/store.svelte.ts`
  - `web/src/lib/api.ts`

### F-08 Slash Suggestion Menu
- Status: `backlog`
- Priority: `medium`
- Goal: When the player types `/`, show suggested commands inline.
- Why:
  Slash commands are acceptable as optional affordances, but they need to be discoverable.
- Likely touch points:
  - `web/src/lib/slash.ts`
  - `web/src/components/Composer.svelte`
  - `web/src/styles/app.css`

### F-09 History Browsing
- Status: `backlog`
- Priority: `medium`
- Goal: Add a more usable long-session history browser.
- Why:
  The user wants this, but it is likely a larger feature and not the first thing to tackle.
- Candidate scope:
  - searchable transcript
  - scene/turn jump
  - better oracle-history browsing
- Likely touch points:
  - `web/src/components/ChatFeed.svelte`
  - `web/src/components/Inspector.svelte`
  - `src/dungeon_master/state_store.py`
  - `src/dungeon_master/api.py`

### F-10 Onboarding / First-Turn Guidance
- Status: `backlog`
- Priority: `medium`
- Goal: Add lightweight onboarding once active play begins.
- Why:
  Setup is guided, but active play still assumes too much implicit knowledge.
- Candidate scope:
  - first-turn helper text
  - explain chat vs slash commands
  - explain inspector / receipts / stop / regenerate
- Likely touch points:
  - `web/src/App.svelte`
  - `web/src/components/Composer.svelte`
  - `web/src/components/StatusStrip.svelte`
  - `web/src/lib/slash.ts`

## Later

### F-11 Optional Explicit Cairn Commands / Controls
- Status: `later`
- Priority: `low`
- Goal: Surface attack/harm/recover/equip as optional slash commands or UI controls.
- Why:
  Useful as backup/discoverability, but not required as the main intended mechanism.
- Note:
  This should stay secondary to the LLM free-text flow.

### F-12 Save Slots / Multiple Campaigns
- Status: `later`
- Priority: `low`
- Goal: Support multiple campaigns / branches / characters without manual file handling.
- Why:
  Nice even for solo use, but explicitly deprioritized for now.

## Tabled

### F-13 Player-Facing Rollback / Checkpoint Restore
- Status: `tabled`
- Priority: `low`
- Reason:
  The user does not want to prioritize cheating-friendly restore flow right now.

### F-14 Player-Facing Correction / Editing Services
- Status: `tabled`
- Priority: `low`
- Reason:
  The user does not want to prioritize manual correction/admin editing surfaces right now.

## Done

- None yet. Move tickets here only after they land and are verified.
