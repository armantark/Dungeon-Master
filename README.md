# Dungeon Master

A personal solo TTRPG harness where Python owns deterministic mechanics and a LiteLLM-routed model is restricted to narration. The frontend is a bespoke Svelte 5 grimoire UI; the backend is a FastAPI server.

## What It Does

- Tracks canonical state in `data/game_state.json` and writes append-only events to `data/events.jsonl`.
- Snapshots a checkpoint into `data/checkpoints/` after every meaningful turn.
- Uses a deterministic oracle for yes/no questions, random events, and scene checks.
- Generates the opening scene, threads, NPCs, and oracle word banks on first launch (or after a reset) using the configured LLM.
- Keeps the LLM out of dice rolls, chaos factor, threads, NPCs, and any state mutation.
- Falls back to deterministic placeholder narration when no model is configured.

## Architecture

```
+------------------+        HTTP / JSON          +-----------------------+
|  Svelte 5 + TS   |  <----------------------->  |       FastAPI         |
|  (web/, Vite)    |        /api/*               |  (dungeon_master.api) |
+------------------+                             +-----------+-----------+
                                                             |
                                                             v
                                          +-----------------------------------+
                                          |        GameService                |
                                          |  - OracleEngine (Python, dice)    |
                                          |  - StateStore   (json + events)   |
                                          |  - CampaignGenerator (LLM bootstrap) |
                                          |  - NarrativeEngine   (LLM via LiteLLM) |
                                          +-----------------------------------+
```

The HTTP surface is intentionally thin: every mutation returns the entire `GameState`, so the frontend never reconciles partial diffs.

## Run

Two processes (one terminal per process is easiest):

```shell
# 1) backend
uv sync
uv run dungeon-master            # serves http://127.0.0.1:8000

# 2) frontend
cd web
npm install
npm run dev                      # serves http://127.0.0.1:5173
```

Open http://127.0.0.1:5173. Vite proxies `/api` to the FastAPI server.

To run the backend with autoreload during development:

```shell
uv run dungeon-master --reload
```

## Configure The Narrative Model

Default provider is OpenRouter with Kimi K2.6 Thinking. Reasoning defaults to `auto`: medium effort for ordinary narration / yes-no, high effort for scene checks and random events.

Copy `.env.example` to `.env` and fill in your key:

```shell
OPENROUTER_API_KEY=
OPENROUTER_API_BASE=https://openrouter.ai/api/v1
LITELLM_MODEL=openrouter/moonshotai/kimi-k2.6
LITELLM_REASONING_EFFORT=auto       # or medium | high to pin
LITELLM_EXCLUDE_REASONING=true
LITELLM_MAX_TOKENS=1800
LITELLM_TEMPERATURE=0.85
OR_APP_NAME=Dungeon Master
DUNGEON_MASTER_STATE_PATH=data/game_state.json
```

To switch models later, change `LITELLM_MODEL` to another LiteLLM model string and provide that provider's required environment variables.

## Test

```shell
uv run ruff check .
uv run mypy src tests
uv run pytest
cd web && npm run check
```

Manual browser checks are documented in `docs/manual-testing.md`.

## Design Note

The oracle is inspired by solo game-master emulators (likelihood, chaos, scene pacing, events, threads, NPC prompts) but uses original tables — no proprietary text from Mythic GME 2e or any other system.
