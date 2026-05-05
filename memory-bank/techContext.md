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
- Vite proxies `/api` -> `http://127.0.0.1:8000`.
- Runtime types are hand-mirrored in `web/src/lib/types.ts` to match `src/dungeon_master/models.py`.

Implemented components:

Backend:

- `src/dungeon_master/api.py`: FastAPI app + routes for state, oracle, action, reset, setup, and SSE streaming.
- `src/dungeon_master/cli.py`: `dungeon-master` console script that runs uvicorn.
- `src/dungeon_master/campaign.py`: model-driven campaign bootstrap and oracle table generation.
- `src/dungeon_master/models.py`: Pydantic state and event schemas, including `CampaignStatus`, `CharacterSheet`, and `InventoryItem`.
- `src/dungeon_master/oracle.py`: deterministic oracle engine.
- `src/dungeon_master/cairn.py`: Cairn 2e-inspired rules engine. Deterministic math stays here (saves, attacks, harm/critical damage/scars, recovery, equipment toggles, derived armor/burden recomputation), while one-time character backfill is now LLM-backed and returns a structured mechanics record plus a practical starting bundle.
- `src/dungeon_master/state_store.py`: JSON state, JSONL event log, timestamped checkpoints, and named pre-narration turn checkpoints for regeneration.
- `src/dungeon_master/narrative.py`: LiteLLM narrative client with retries, Kimi/OpenRouter defaults, fallback narration, and streaming helpers that emit `CompletionDelta` chunks carrying both prose and reasoning.
- `src/dungeon_master/service.py`: application service coordinating oracle, state, narration, and campaign generation. It now also exposes result-bearing and streaming setup methods so setup and active play share one backend transport pattern.
- `src/dungeon_master/turn_router.py`: LiteLLM-backed natural-language classifier for `/api/turn`. It returns structured route decisions (`player_action`, `yes_no`, `random_event`, `scene_check`, `save`) and falls back to `player_action` if the model is unavailable rather than using regex inference.
- `src/dungeon_master/settings.py`: environment-backed state path configuration.

Frontend:

- `web/src/main.ts`, `web/src/App.svelte`: entry + setup-aware layout (CharacterSetup before campaign start; StatusStrip → CharacterFolio + ChatFeed → Composer → Inspector once active).
- `web/src/lib/api.ts`: thin fetch wrapper, now also exposing character template/draft/finalize/start and message-regenerate endpoints.
- `web/src/lib/store.svelte.ts`: single runes-based `GameStore` owning `state`, `isLoading`, `error`, `rollPhase`, `pendingOracle`, `cancelLabel`, ephemeral `notes`, and `inspectorOpen`. Exposes setup actions, `submit(rawText)`, `regenerateMessage(eventId)`, and `cancelCurrentRequest()`.
- `web/src/lib/slash.ts` + `slash.test.ts`: pure slash-command parser (`/ask`, `/event`, `/scene`, `/chaos`, `/reset`, `/help`) with Vitest coverage.
- `web/src/lib/character.ts` + `character.test.ts`: pure setup helpers (`deriveSetupMode`, `blankCharacterDraft`) plus latest-message regeneration eligibility helper (`message-actions.ts`).
- `web/src/lib/quiz.ts` + `quiz.test.ts`: assist-mode interview helpers (answer state, validation, payload builder).
- `web/src/lib/cairn.ts` + `cairn.test.ts`: pure Cairn formatting helpers (defaults mirroring `models.py`, render gating, burden tier, priority-ordered status badges, ability/stance/rest-kind labels, item tag labels, and the exhaustive `cairnHeadline` switch over `save | attack | harm | recovery`).
- `web/src/lib/types.ts`: TS mirrors of `GameState`, `OracleOutcome`, plus the new Cairn enums and nested mechanics state (`CairnAbility`, `AttackStance`, `CairnRestKind`, `CairnItemTag`, `CairnMechanicsSource`, `CairnItemState`, `CairnCharacterState`, `CairnResolution`). The `OracleKind` union now includes `save | attack | harm | recovery` so the receipt switch is exhaustive at compile time.
- `web/src/styles/app.css`: bespoke pigment palette (`--ink-*`, `--paper-*`, `--gold-*`, `--rust-*`), three-voice type system (Cormorant body / IM Fell display / Alagard pixel engine voice), parchment + iron surfaces, deckled-edge SVG mask, film-grain overlay, button/form/tag styling. Adds a `.tag--cairn` flavor (verdigris-green tinted) for receipt strips of Cairn-flavored outcomes.
- `web/public/fonts/alagard.ttf`: CC-BY pixel font by Hewett Tsoi, used for the engine voice. VT323 is the Google-Fonts fallback.
- `web/src/components/`: `StatusStrip`, `CharacterSetup`, `CharacterTemplateCard`, `CharacterEditor`, `LoadingPanel`, `CharacterFolio`, `CairnReadout`, `ChatFeed`, `ChatMessage`, `MessageActions`, `MechanicalReceipt`, `Composer`, `Inspector`, `ChaosDial`, `Drawer`, `ThreadsPanel`, `NPCsPanel`, `NotesEditor`. `CairnReadout.svelte` is the new shared read-only mechanics surface used by `CharacterFolio` (active play) and `CharacterEditor` (post-backfill draft preview). Removed in the chat-first pivot: `SceneCard`, `OracleConsole`, `PlayerCommand`, `ActionLog`, `DiceTumbler` (the dice now live inline in `MechanicalReceipt`).

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
- `LITELLM_EXCLUDE_REASONING=true`

OpenRouter's model card lists the underlying model slug as `moonshotai/kimi-k2.6`, with 262K context and reasoning token support. LiteLLM uses the provider-prefixed model string `openrouter/moonshotai/kimi-k2.6`. The app defaults to a medium/high task-based reasoning policy instead of `xhigh`, because excessive thinking may make the model overcomplicate or hallucinate.

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
- `uv run pytest` (currently 53 passing)
- `cd web && npm run check`
- `cd web && npm test`  (Vitest — currently covers `lib/slash.ts`, `lib/character.ts`, `lib/message-actions.ts`, `lib/quiz.ts`, and `lib/cairn.ts`; 43 passing)
- `cd web && npm run build`
- `uv run dungeon-master` (backend) + `cd web && npm run dev` (frontend) for browser smoke tests via Pinchtab. Note: Pinchtab's `browser_fill` and `browser_type` set the DOM `value` attribute but do not always dispatch the `input` event Svelte 5's `bind:value` listens for; for end-to-end UI verification use a real keyboard, or rely on the slash-parser unit tests + the API integration tests to lock in the routing contract.
- Backend-only Cairn smoke: `POST /api/cairn/save`, `/api/cairn/attack`, `/api/cairn/harm`, `/api/cairn/recover`, and `/api/cairn/equip` now exist and return the full `GameState`.

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
