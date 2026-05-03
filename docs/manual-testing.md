# Manual Testing

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

## Live Model Smoke Test

After putting an `OPENROUTER_API_KEY` in `.env`:

1. Reset the campaign (inspector → Reset).
2. Send a freeform action.
3. Confirm the response is real prose from Kimi K2.6 — not the "No model is configured, so this is deterministic placeholder narration." fallback, and not an `[Narrative API unavailable: …]` bracket.

If the fallback is hitting, open `data/events.jsonl` and look for the bracketed error in the most recent narrative event. That tells you whether the failure is auth, parameter rejection, or timeout, and points at the right knob in `.env`.

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
