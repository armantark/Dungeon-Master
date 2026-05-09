# Manual Testing

## Fixture Library Harness

Use this when you need representative browser data for continuity-heavy UI
branches without touching your real campaign.

1. Seed an isolated fixture library:

```shell
uv run dungeon-master-fixtures \
  --state-path "/tmp/dungeon-master-fixtures/game_state.json" \
  --force
```

1. Start an isolated backend against the fixture root on a spare port:

```shell
DUNGEON_MASTER_STATE_PATH="/tmp/dungeon-master-fixtures/game_state.json" \
uv run dungeon-master --port 8001
```

1. Start a second frontend dev server that proxies `/api` to that backend:

```shell
cd web
VITE_API_PROXY_TARGET="http://127.0.0.1:8001" npm run dev -- --port 5174
```

1. Open `http://localhost:5174`.
1. Confirm the app auto-loads the `Fixture Bellringer` save.
1. In chat, expand the latest mechanical receipt. Confirm it shows both `Threads`
   and `Figures` pills.
1. Click the thread pills and confirm the Inspector opens to `Threads`, scrolls
   the right card into view, and flashes it.
1. Click the NPC pills and confirm the Inspector opens to `NPCs`, scrolls the
   right card into view, and flashes it.
1. In `NPCs`, confirm `The ash-veiled bellringer` is rendered with the `known by
   sign` cue and that the hidden abbot is not shown anywhere player-facing.
1. Open the save shelf and switch to `Fixture Archive`. Confirm the shelf marks
    it as ended and that the archived campaign loads without mutating the active
    continuity fixture.

## Browser Smoke Test

Walk through this from a clean state (delete `data/game_state.json` if you want a fresh campaign).

1. Start the backend: `uv run dungeon-master`. Confirm the server logs `Uvicorn running on http://127.0.0.1:8000`.
2. Start the frontend: `cd web && npm run dev`. Confirm Vite logs `Local: http://localhost:5173/`.
3. Open `http://localhost:5173`.
4. Confirm you land in character creation, not in the chat immediately. The screen should offer three entry paths: `Templates`, `Scratch`, and `Assist`.
5. Click `Templates`. Confirm 4 archetypal dark-fantasy survivors appear. Use `Quickstart` on one template and confirm the campaign begins generating around that character.
6. Reset back to setup (`Reset campaign` from the inspector or `/api/state/reset`), then choose `Scratch`. Confirm you can open a blank editable character sheet with name, archetype, backstory, drive, flaw, condition, and inventory.
7. Reset again, choose `Assist`, enter a one- or two-sentence concept, and generate a draft. Confirm the AI fills the character sheet and you can still edit every field before starting.
8. Once the campaign is active, confirm the left folio stays visible with character identity, condition, and inventory.
9. Type a freeform action (`I sift the ash for fresh boot tracks.`) and press `Cmd/Ctrl + Enter`. Confirm the player line appears immediately and the DM responds with narration. No dice receipt under it.
10. Ask a plain yes/no question (`Is the abbey gate watched? [likely]`). Confirm the backend routes it through the oracle even without `/ask`, then a DM response appears with a collapsible mechanical receipt under it. Expand the receipt and verify the d100 roll, the likelihood, and the chaos-factor-at-the-time line up.
11. Click `Regenerate response` on the latest DM reply. Confirm the reply is replaced, a `Narrative regenerated` system event is inserted, and the oracle receipt remains the same (same deterministic outcome, no reroll).
12. Start a long-running generation (campaign start, assist draft, or response generation) and click the `Stop ...` button while the request is in-flight. Confirm the UI stops waiting and loading clears.
13. Click the **Inspect** button (top-right). Confirm the drawer opens with compact collapsed sections for `Threads`, `NPCs`, `Notes`, and `Oracle history`, with no doubled title text on hover.
14. In the inspector, change the chaos factor to 8 with `+` and `Commit`. Close the drawer. Confirm the badge in the top strip reads `8`.
15. Send `/help`. Confirm the engine voice prints the explicit slash-command list as a system message in the chat. Slash commands remain the manual override path when you want exact control over routing.
16. Refresh the browser. Confirm the current campaign/setup state persists exactly as it was.
17. If you are testing a pre-Cairn character/save, start or reload the campaign once and confirm the backend has backfilled `state.character.cairn` on the next `/api/state` response. This is the one-time migration path that preserves the authored sheet instead of asking the player to recreate it.

## Party Folio Smoke

Use this once a save has at least one active companion, hireling, or animal in
`state.party_members`.

1. Open an active campaign with one active party member.
1. Confirm the left folio shows a tab strip with the protagonist plus the active
   party member(s).
1. Click each tab. Confirm the identity plate, Cairn readout, burden meter, and
   inventory list all switch to that actor.
1. Confirm inactive party members do not appear as tabs.
1. Make a companion-attributed action in natural language (for example, ask the
   companion to attack or transfer an item by name). Expand the resulting
   receipt and confirm it shows the actor name when the backend attributes the
   Cairn resolution.
1. Refresh the page. Confirm the selected save still loads and the tab strip
   renders from canonical `party_members`.

## Streaming Smoke Test (combat-streaming branch)

These checks exercise the NDJSON streaming transport, the provisional DM bubble, the persisted thinking pane, the detach/reattach contract, and the combat tracker. They assume the backend has shipped its half of the contract (`/api/turn/stream`, `/api/action/stream`, `/api/messages/{id}/regenerate/stream`, `/api/campaign/start/stream`, `/api/character/quiz/stream`, `/api/character/draft/stream`, `/api/character/draft/quizzed/stream`, and `GET /api/requests/{request_id}/stream` for reattach). If the backend hasn't shipped any given endpoint, the frontend transparently falls back to the unary version — confirm the fallback path also still works.

1. From an active campaign, send a freeform action like `I check the threshold for old wax.`. Confirm a provisional DM bubble appears immediately (no full-response wait), prose tokens stream into it letter by letter, the blinking caret tracks the latest token, and the bubble is replaced by the canonical event when the stream completes (no double-bubble flicker).
2. While the stream is in flight, click `Stop response`. Confirm the bubble freezes wherever it was and the loading state clears. Sending another turn afterwards should work normally.
3. Ask a yes/no question (`Will the door give? [unlikely]`). Confirm the receipt strip (`yes_no` tag, d100 roll) pins under the bubble when the canonical state lands. (Note: the backend currently emits `mechanics_ready` only as the trailing `final_state` rather than mid-stream; an early-pin event is a future enhancement, not a regression.)
4. For a build that includes the hybrid continuity pass, send a lore/clarification turn that may establish durable canon (`Do we know his name? Is he of legend?`). Confirm prose begins streaming first, and if the backend emits a late continuity stage (for example `Reconciling continuity`) it appears in the checklist after `Streaming narration` has begun rather than blocking prose. The turn should still end with a single `final_state`.
5. Open the `Reasoning trace` strip on the latest persisted DM message. Confirm the trace is collapsed by default, expands to show the model's thinking, is rendered in the engine (Alagard pixel) voice, and persists across a page refresh (the backend writes it onto the `GameEvent`). If the turn included a late continuity stage, confirm the persisted checklist includes it with the correct order and timing.
6. In the assist setup flow, type a concept and click `Begin interview`. Confirm the LoadingPanel surface shows a live `Thinking…` strip plus a tail-end preview of the model's prose as it streams. Cancel mid-stream with `Stop interview` and confirm the panel clears cleanly.
7. Click `Generate draft` from the review screen. Confirm the same streaming surface appears — Thinking strip + prose preview — and the final draft lands in the editor when streaming completes.
8. Trigger combat in narrative (`I attack the marauder.`). Confirm the top StatusStrip grows a `Combat · Round 1 · DEX save to act` badge, the inspector auto-shows a default-open `Combat` drawer with the foe's HP/Armor/STR/DEX/WIL, the foe's HP bar tier shifts colors as they take damage, and the headline drops the `DEX save to act` suffix once the player is marked ready.
9. When all foes drop to 0 HP, confirm the encounter clears: the StatusStrip combat badge disappears, and the inspector either hides the drawer entirely or shows the cleared summary.
10. Start a streamed turn, then refresh the page before the model finishes. Confirm:
   - The provisional DM bubble re-appears within a beat of the bootstrap completing, with the meta tag reading `resuming…` (verdigris accent) instead of `streaming…`.
   - Prose continues to stream into that bubble until the canonical event lands.
   - The final committed `state.action_log` contains the finished narrative exactly once.
   - If the turn shape includes a late continuity stage, the resumed checklist preserves that stage and its status transitions instead of dropping it after the first content token.
   - localStorage key `dm.stream-resume.<save_id>` is cleared after the final lands. (Inspect via DevTools → Application → Local Storage.)
   - If you start another turn, refresh, and wait more than 10 minutes before reloading, the descriptor TTL evicts itself silently and the next bootstrap behaves like a normal cold start.
11. With the backend console visible (or logs captured), confirm each streamed turn emits one `turn.router ...` line, one `continuity.classifier ...` line when pre-narration continuity actually runs, and one `llm.call ...` line per model request. The minimum useful fields are `route`, `profile`, `request_id`, token counts when available, and `duration_ms`. Set `DM_LOG_LEVEL=INFO` in `.env` if those lines are not visible.
12. Force a streaming endpoint to 404 by stubbing it on the backend (or run an older server). Confirm the unary fallback still produces the final state — the only visible difference is no provisional bubble or live thinking strip.

## Live Model Smoke Test

After putting an `OPENROUTER_API_KEY` in `.env`:

1. Reset the campaign (inspector → Reset).
2. Send a freeform action.
3. Confirm the response is real prose from Kimi K2.6 — not the "No model is configured, so this is deterministic placeholder narration." fallback, and not an `[Narrative API unavailable: …]` bracket.

If the fallback is hitting, open `data/events.jsonl` and look for the bracketed error in the most recent narrative event. That tells you whether the failure is auth, parameter rejection, or timeout, and points at the right knob in `.env`.

## Cairn Backend Smoke

These checks exercise the backend rules layer before the frontend exposes dedicated controls for it.

1. Start from an active campaign.
1. Run:

```shell
curl -s -X POST http://127.0.0.1:8000/api/cairn/save \
  -H "Content-Type: application/json" \
  -d '{"ability":"DEX","reason":"Balance across the abbey beam."}' | python3 -m json.tool
```

Confirm the latest `oracle_history` entry has `kind: "save"` and a nested `cairn.ability: "DEX"`.

1. Fetch state and copy the current primary weapon id:

```shell
curl -s http://127.0.0.1:8000/api/state | python3 -m json.tool
```

1. Run:

```shell
curl -s -X POST http://127.0.0.1:8000/api/cairn/attack \
  -H "Content-Type: application/json" \
  -d '{"target_name":"Abbey ghoul","target_armor":1}' | python3 -m json.tool
```

Confirm the latest `oracle_history` entry has `kind: "attack"` and a nested `cairn.damage_after_armor`.

1. Run:

```shell
curl -s -X POST http://127.0.0.1:8000/api/cairn/harm \
  -H "Content-Type: application/json" \
  -d '{"amount":2,"source":"Falling masonry","in_combat":true,"armor_applies":false}' | python3 -m json.tool
```

Confirm HP (or STR on overflow) changes in `state.character.cairn`.

1. Run:

```shell
curl -s -X POST http://127.0.0.1:8000/api/cairn/recover \
  -H "Content-Type: application/json" \
  -d '{"kind":"breather"}' | python3 -m json.tool
```

Confirm the latest `oracle_history` entry has `kind: "recovery"` and HP is restored if the character is not deprived.

## Cairn Item-Power UI Smoke

Use an isolated save-library root when checking spellbook / scroll / relic /
holy-relic rendering. The useful branches are:

1. Inventory item shows its typed power title (for example `Holy relic · ...`),
   summary, uses, and cost/risk chips such as `WIL in danger`.
2. A structured item-use receipt collapses as an `item` receipt, not generic
   `player_action`.
3. Expanding the receipt shows item, power, effect, effect summary, uses,
   recharge, and any HP/STR/DEX/WIL/Fatigue deltas.
4. Reload an older save whose inventory items predate `cairn.power`; the folio
   should render without crashing and simply omit the power block.

## Memory Sidecar Smoke

These checks verify the compacted GM-note memory layer (`data/memory.json`) without mutating your real campaign.

1. Start an isolated backend with a temporary state path and fallback narration so the turn commits quickly:

```shell
OPENROUTER_API_KEY="" \
DUNGEON_MASTER_STATE_PATH="/tmp/dm-memory-fallback/game_state.json" \
uv run dungeon-master --port 8002
```

1. In a second terminal, seed a temporary active save:

```shell
uv run python - <<'PY'
from pathlib import Path
from dungeon_master.models import CairnMechanicsSource
from dungeon_master.state_store import StateStore
from tests.factories import sample_state

state = sample_state()
state.character.cairn.source = CairnMechanicsSource.EXPLICIT
for item in state.character.inventory:
    item.cairn.source = CairnMechanicsSource.EXPLICIT

StateStore(Path("/tmp/dm-memory-fallback/game_state.json")).save(
    state,
    create_checkpoint=True,
)
PY
```

1. Commit a deterministic oracle turn:

```shell
curl -s -X POST http://127.0.0.1:8002/api/oracle/yes-no \
  -H "Content-Type: application/json" \
  -d '{"question":"Is the abbey gate watched?","likelihood":"Likely"}' \
  | python3 -m json.tool
```

1. Confirm `/tmp/dm-memory-fallback/memory.json` now exists and contains:
   - `turn_count: 1`
   - a `recent_turn_summaries` entry for the new oracle turn
   - a non-empty `current_scene_summary`
   - populated `thread_memory` / `npc_memory` / `location_memory` / `open_loops`

1. In the live browser app, submit a turn and then click `Stop response` while the stream is active. Confirm the UI returns to idle cleanly. Then verify that cancelling did **not** contaminate the next committed memory state (cancelled turns should not appear in `data/memory.json`).

## Developer Knobs (`.env`)

Everything in `.env` is a developer / debugging dial, not a player-facing control. The defaults are set so a fresh checkout works against OpenRouter Kimi K2.6 with task-based reasoning.

| Variable | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | Auth for OpenRouter. Leave empty to force fallback narration. |
| `LITELLM_MODEL` | Any LiteLLM model string (e.g. `openrouter/anthropic/claude-3.5-sonnet`). |
| `LITELLM_REASONING_EFFORT` | `auto` (medium for chat / yes-no, high for events / scene checks), or pin to `medium` / `high`. |
| `LITELLM_EXCLUDE_REASONING` | `true` to drop reasoning tokens from the response payload. |
| `LITELLM_MAX_TOKENS` / `LITELLM_TEMPERATURE` / `LITELLM_TIMEOUT_SECONDS` / `LITELLM_MAX_RETRIES` | Standard generation knobs. |
| `OR_APP_NAME` / `OR_SITE_URL` | OpenRouter routing identity. |
| `DUNGEON_MASTER_STATE_PATH` | Override the canonical state file location. |

If a switch ever feels like it should be on the UI instead of the dotenv, that's a signal it's a player-facing setting and should be promoted to a real control.

## LLM Preset Switching

These steps cover the in-app `Narrative model` setting that swaps between Kimi (single-model OpenRouter) and the Gemini split (Flash for structured tool calls + Pro for narration / reasoning). Both `OPENROUTER_API_KEY` and `GEMINI_API_KEY` must be present in `.env` for the full round-trip; if one is missing, that preset surfaces as `Unavailable` with the exact env vars to add.

Use Pinchtab (`https://github.com/pinchtab/pinchtab`) for the browser steps so the recording is reproducible:

1. Start the backend and frontend as in the [Browser Smoke Test](#browser-smoke-test) section. With both keys set, the default preset is Kimi (matches `data/runtime_settings.json` on a fresh install).
2. Open the system menu (top-right hamburger) and pick `Narrative model`. Confirm the modal opens, the `Active` readout shows three Kimi `openrouter/...` slugs, and the `Kimi (OpenRouter)` card is checked.
3. Click the `Gemini split` card. Confirm:
   - The button briefly enters a `Saving…` state and is disabled.
   - On success, the `Active` readout flips to `gemini/gemini-3-flash-preview` (structured) and `gemini/gemini-3.1-pro-preview` (narration / reasoning).
   - `data/runtime_settings.json` on disk now contains `"llm_preset": "gemini_split"`.
4. Submit a free-text turn (`I look around`). Watch the backend log: planner / mechanics / NPC-updater calls should be against `gemini-3-flash-preview`; the narration stage should be against `gemini-3.1-pro-preview`.
5. Start a long-running turn, immediately reopen the modal, and try clicking `Kimi`. Confirm the modal renders an inline error reading "Cannot change LLM settings while a request is still in flight." and the radio remains on Gemini split. Wait for the turn to finish and retry the swap — it should now succeed.
6. With `GEMINI_API_KEY` empty in `.env`, restart the backend, open the modal, and confirm the `Gemini split` card is greyed out, shows an `Unavailable` badge, and lists `GEMINI_API_KEY` under "Missing environment variables". Confirm clicking the card does nothing.
7. Reload the browser. Confirm the active preset persists across reloads (the modal still reflects the disk-resident `runtime_settings.json`).

## Desktop Beta BYOK

These steps cover the new Tauri desktop beta shell and the first-run BYOK flow.

1. Build the backend sidecar:

   ```shell
   cd web
   npm run sidecar:build
   ```

2. If Rust is installed locally, launch the desktop shell:

   ```shell
   npm run tauri:dev
   ```

3. Ensure there is no usable provider key in the environment (`OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `LITELLM_API_KEY` unset or empty) and remove any prior desktop credential file in the app-data directory if you want a true first-run check.
4. Confirm the desktop app opens to the BYOK overlay before the save library or character setup appears.
5. Choose `Gemini` or `OpenRouter`, paste a valid key, and click `Save key`. Confirm:
   - The overlay blocks close while saving.
   - Gemini auto-selects the `Gemini split` preset after save; OpenRouter keeps `Kimi`.
   - The app proceeds into the normal save-library / setup flow without requiring `.env`.
6. Open `Narrative model` from the system menu. Confirm the provider-key section shows the configured provider as either `Saved in app settings` or `Loaded from .env`, with the key masked.
7. Quit and relaunch the desktop app. Confirm the BYOK overlay does not reappear and the masked provider status is still present.

If Rust is not installed on the local machine, treat the sidecar build (`npm run sidecar:build`) plus the GitHub Actions desktop-release workflow as the current verification surface for the desktop beta.
