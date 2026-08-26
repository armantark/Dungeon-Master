# Tech Context

## Repository

The solo project lives at `/Users/ArmanTarkhanian1/Desktop/dungeon-master` and commits directly to local `main`. Do not push unless the user explicitly asks.

## Runtime stack

Backend:

- Python 3.12 managed with `uv`.
- FastAPI and Uvicorn for HTTP/JSON and NDJSON streaming.
- Pydantic for state, request, event, and structured model-output contracts.
- LiteLLM for provider-independent model calls with retry support.
- Local JSON, JSONL, and checkpoint directories for canonical single-player persistence.

Frontend:

- Svelte 5 runes, TypeScript, and Vite; no SvelteKit.
- Vanilla CSS with project-specific pigments, fonts, textures, and layouts.
- Three.js only for the development architecture map.
- Tauri 2 wraps the same frontend and a bundled FastAPI sidecar for desktop builds.
- Vite proxies `/api` to `http://127.0.0.1:8000` by default; `VITE_API_PROXY_TARGET` supports isolated development backends.

## Source ownership

Backend:

- `src/dungeon_master/api.py`: stable FastAPI import facade.
- `src/dungeon_master/transport/http/`: app assembly, request schemas, dependency/runtime wiring, route groups, and NDJSON response adaptation.
- `src/dungeon_master/transport/stream_runtime.py`: retained stream sessions, cancellation, replay, and live-tail subscribers.
- `src/dungeon_master/service.py`: application facade for campaign lifecycle, persistence, direct commands, regeneration, and stream boundaries.
- `src/dungeon_master/application/turn_plan_execution.py`: composed typed-plan executor with explicit mechanics, oracle, capability-guard, and LLM dependencies.
- `src/dungeon_master/application/continuity.py` and `turn_commit.py`: post-narration proposals and canonical commit tail.
- `src/dungeon_master/mechanics/`: combat, character generation, inventory, and survival rules. `cairn.py` is the public facade.
- `src/dungeon_master/llm/completion/`: provider transport and completion contracts.
- `src/dungeon_master/llm/planning/`: typed plan contracts, prompts, review gates, normalization, and routing. `turn_router.py` is the public facade.
- `src/dungeon_master/llm/narration/`: prose generation. `narrative.py` is the public facade.
- `src/dungeon_master/memory/`: bounded context projection, retrieval, rendering, and the public `MemoryManager` interface.
- `src/dungeon_master/generation/`: campaign and character generation workflows.
- `src/dungeon_master/state_store.py` and `save_library.py`: canonical local persistence, checkpoints, and save selection.

Frontend:

- `web/src/features/`: Svelte UI grouped by combat, inspector, play, saves, settings, and setup.
- `web/src/contracts/`: TypeScript wire contracts grouped by backend domain. `web/src/lib/types.ts` is the public facade.
- `web/src/state/`: the rune-backed `GameStore` plus campaign, save-library, runtime-settings, streaming, and stream-terminal workflows. `web/src/lib/store.svelte.ts` is the public facade.
- `web/src/lib/api.ts`: browser/Tauri HTTP client.
- `web/src/styles/`: shared visual system.
- `web/src-tauri/`: desktop host, sidecar lifecycle, and bundle configuration.
- `scripts/build_tauri_sidecar.py`: PyInstaller sidecar builder.
- `.github/workflows/desktop-release.yml`: desktop release pipeline.

## Persistence

- `data/library.json` indexes save slots.
- `data/saves/<save_id>/game_state.json` is campaign canon.
- `events.jsonl` is the append-only event record.
- `checkpoints/` and `turn-checkpoints/` support recovery and regeneration.
- `memory.json` is bounded, derived model context. It is disposable and rebuildable from canonical state and committed turns.
- The current file-backed design assumes one local writer. SQLite is the next durability step if atomic multi-record commits or concurrent local writers become necessary; hosted Postgres becomes justified with accounts or multiplayer.

## Model configuration

Do not change configured models or API signatures unless the user explicitly asks. The checked-in `data/runtime_settings.json` currently selects `gemini_split`: Gemini Flash for structured planning/update work and Gemini Pro for narration/heavier generation. The `kimi` preset remains available through LiteLLM.

Credential resolution for the desktop build is stored app-data key, then environment, then unavailable. Terminal development can use `.env`.

## Type and style standards

Python:

- Ruff targets Python 3.12 with a 100-character line limit and broad lint coverage.
- Mypy runs in strict mode over `src` and `tests`.
- Public and private functions should use precise annotations; avoid untyped `Any` and validate model/network boundaries at runtime.

TypeScript and Svelte:

- Prettier with `prettier-plugin-svelte` owns formatting.
- ESLint uses type-aware TypeScript rules, Svelte recommended rules, and `eslint-config-prettier`; warnings fail the run.
- `svelte-check` owns Svelte and TypeScript component diagnostics.
- Frontend contracts are hand-mirrored from Pydantic models. Revisit code generation if contract churn makes that error-prone.

## Verification commands

```shell
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest
cd web
npm run format:check
npm run lint
npm run check
NODE_OPTIONS=--no-experimental-webstorage npm run test -- --maxWorkers=1
npm run build
npm audit --audit-level=moderate
```

Use `uv run dungeon-master-fixtures --state-path <temporary-path> --force` for isolated manual browser checks. Browser work uses PinchTab. Do not test first against a live campaign.

## Operational constraints

- Python owns mechanics, validation, pipeline order, cancellation boundaries, and canonical commits.
- Models produce typed semantic proposals and prose; they do not write campaign state directly.
- Mutating HTTP operations return a complete `GameState`; the frontend replaces its local mirror.
- Streaming work is retained by request ID and remains uncommitted until the terminal commit boundary.
- LLM/network calls need bounded retries. Large paid jobs need checkpoints; small jobs should stay simple.
- The backend binds to localhost and intentionally has no auth. Accounts, authorization, or remote hosting require a new security boundary.
- Local file persistence needs replacement or explicit locking before concurrent writers are allowed.
- Do not copy proprietary game tables verbatim; use original, licensed, or open material.
