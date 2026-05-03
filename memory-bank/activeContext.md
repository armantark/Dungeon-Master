# Active Context

## Current Focus

The active task has moved from planning to building a fully fledged personal agentic TTRPG/AI game-master system.

The most recent source-note state is:

- The user is not committed to OSR.
- OSR entered the discussion only because it appeared in a Discord server description.
- A Mythic GME-style deterministic oracle is the preferred mechanical backbone.
- Ironsworn is a secondary option but is less system-agnostic.
- Full OSR, D&D 5e, or Pathfinder mechanics are considered too heavy for the current architecture unless they clearly improve personal play.
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
- Bespoke Svelte 5 + Vite + TS frontend lives in `web/`, with vanilla CSS and the "Oracle's Ledger" aesthetic.
- Frontend layout is: top status strip (`StatusStrip.svelte`) → flowing chat column (`ChatFeed.svelte` + `ChatMessage.svelte` + `MechanicalReceipt.svelte`) → sticky composer (`Composer.svelte`); inspector drawer (`Inspector.svelte`) slides in from the right edge holding `ChaosDial`, threads, NPCs, notes, and full oracle history.
- A persistent left `CharacterFolio.svelte` now sits beside the chat on desktop widths. It shows the structured character sheet, condition, and inventory so identity/gear stay available during play without opening the inspector.
- The inspector is now a compact reference drawer, not a nested-scroll dashboard. All reference sections are collapsed by default, chaos is a tight control row instead of the large wax seal, drawer bodies are height-capped, and long thread/NPC text is line-clamped.
- Campaign flow now has an explicit setup lifecycle: `character_creation` -> `ready_to_start` -> `active`. New sessions no longer auto-generate a world on first load; they enter `CharacterSetup.svelte` first.
- Character creation now supports three flows: archetypal AI templates, blank scratch sheet, and an **AI-assisted interview** ("assist") path. The assist path is now multi-step: the player types a one-line concept, the LLM generates a 4–6 question interview tailored to that concept (each question has 3–5 options + a free-text "Other (write your own)"), the player answers, an optional "Anything else?" review note is collected, and only then is the draft generated from concept + answers + final note. Every generation phase shows a `LoadingPanel.svelte` indicator with a same-place cancel control.
- LLM token budgets for character generation: Kimi K2.6 Thinking always burns ~2-3k reasoning tokens regardless of the requested `effort` setting, so the previous 2200/2400-token caps were silently producing zero content (`finish_reason=length`, `content=None`). All character/quiz/draft requests now use `medium` reasoning + `max_tokens=12000`; campaign generation keeps `high` reasoning but with the same 12000 budget. Quiz generation uses `low` reasoning specifically because it's structured authoring with short strings.
- All generation fallbacks now log via `logger.exception` so silent fallbacks (the old "draft looks generic / templated") are visible in the uvicorn logs instead of disappearing into the network.
- Latest DM response now gets a `Regenerate response` button. Regeneration restores the pre-narration checkpoint for that turn, preserves the deterministic oracle outcome/dice, and appends a system audit event before writing the repaired narrative.
- The client now exposes a best-effort `Stop` button during long-running requests via `AbortController`. This stops waiting in the UI and clears loading state even though the backend request model is still synchronous.
- Player input has two routing layers:
  - Explicit slash commands are parsed by `web/src/lib/slash.ts`: `/ask <q> [hint]`, `/event`, `/scene <body>`, `/chaos <n>`, `/reset`, `/help`. Slash hints are unit-tested in `web/src/lib/slash.test.ts` (Vitest).
  - Bare chat is sent to backend `/api/turn`, where `src/dungeon_master/turn_router.py` conservatively routes obvious yes/no questions, scene transitions, and random-event prompts through deterministic mechanics before narration. Ambiguous input remains narrative-only.
- `web/public/fonts/alagard.ttf` (CC-BY) is committed locally; `VT323` from Google Fonts is the auto-fallback if the file is missing.
- `GameState.character` holds structured character/inventory data. Old saves remain compatible: missing character sheets are seeded from `player_notes`, including legacy rusted-skewer/map detection for the current campaign.
- `CharacterSheet` is richer now: `name`, `archetype`, `epithet`, `backstory`, `drive`, `flaw`, `condition`, `inventory`.
- Tests under `tests/` cover the oracle, state store, narrative engine, service (including the new `generate_character_quiz` and `generate_quizzed_character_draft` flows), and FastAPI routes (including `POST /api/character/quiz` and `POST /api/character/draft/quizzed`); `web/` tests cover the slash parser, character helpers, message regeneration gate, and the new quiz answer builder/validator (`web/src/lib/quiz.test.ts`).
- Manual browser testing instructions exist at `docs/manual-testing.md` (now a product walkthrough; env knobs moved to a short developer-knobs appendix).
- Campaign opening content and oracle word banks are generated at campaign initialization rather than baked into `models.py` or `oracle.py`.

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

Open:

- Whether to refine the original oracle tables or replace them with user-supplied licensed/open material.
- Whether the lightweight service layer is enough or a formal graph framework should be added later.
- Whether to add a UI text box for user-authored campaign seeds before generation.
- Whether to expose model switching controls in the UI instead of keeping them environment-only.
- Whether to add checkpoint browse / rollback controls to the frontend.

## Important User Preferences

- The desired game tone is traditional, gritty, oppressive dark fantasy, and apolitical, with a vibe closer to `Berserk` or `Fear & Hunger`.
- The user wants to avoid social friction from public Discord or local groups.
- The user is interested in software architecture that solves LLM reliability problems.
- The user values strong state tracking, retries, and checkpointing.
- The user prefers not to waste energy on dead communities or excessive setup.
- The user is comfortable with Cursor doing substantial scaffolding.
- The user wants a serious personal enjoyment project, not a business-client MVP. Avoid bloat, but do not underbuild for the sake of artificial minimalism.

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

1. Upgrade `TurnRouter` from conservative deterministic heuristics to an optional LLM intent classifier using the existing LiteLLM config, with deterministic heuristics as fallback.
2. Let the DM call mechanics from inside narration: the prompt + LiteLLM tool-calling so a scene like "I creep up to the gate" can autonomously trigger a scene check before narrating the result.
3. Add a real server-side cancellation/cutoff mechanism for long-running LLM calls so `Stop response` can halt generation, not just abort the browser wait.
4. Add thread/NPC editing controls in the inspector drawer.
5. Add a checkpoint browser + rollback panel in the inspector.
6. Add richer setting import (paste-in seed, world-bible upload) before campaign generation if desired.
7. Decide whether to refine the model-generated oracle tables or expose them for manual editing in the UI.

## Caution

Do not overfit the app to Scarlet Heroes or OSR unless the user explicitly chooses that direction. The project is about a reliable AI-assisted game-master harness first; the oracle/rules layer should remain replaceable.

Also avoid copying Mythic GME 2e tables verbatim unless the user supplies licensed material or chooses an open alternative. The system can implement an original deterministic oracle with the same general roles: likelihood, chaos, scene pacing, events, threads, and NPC prompts.
