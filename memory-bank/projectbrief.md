# Project Brief

## Project Identity

Working name: AI Game Master / Dungeon Master.

This project is intended to turn an exploratory TTRPG interest into a controlled solo or small-table game experience. The latest direction is a fully fledged personal agentic game system that uses a deterministic solo oracle engine for mechanics and a locked-down LLM narrative layer for prose, without bloated business-MVP abstractions.

## Core Goal

Build a low-friction TTRPG experience that avoids the main blockers discovered in the source note:

- Long scheduled voice calls with strangers are undesirable.
- Public TTRPG spaces may be culturally or politically misaligned.
- Dormant Discord servers are unlikely to produce actual play.
- Pure solo TTRPG play may feel too close to creative writing unless the system provides enough momentum.
- A raw LLM prompt is not reliable enough for long-running rules and inventory state.

The project should therefore provide the feeling of a responsive game master while keeping game state and mechanical outcomes outside the model as strict sources of truth.

## Current Product Direction

The project now ships as a FastAPI backend plus a bespoke Svelte 5 + Vite + TypeScript "Oracle's Ledger" UI. Streamlit was explored early and then discarded once the user chose a chat-first grimoire interface with custom visuals, richer layout control, and more game-like feedback.

The project is not married to OSR, 5e, or any other single chassis. Earlier AI-generated exploration leaned heavily on Mythic GME-style oracle play, but the user clarified that those were exploratory assumptions rather than approved design commitments. The actual product requirement is a **fun, rules-grounded experience** with enough structure to feel like a real game rather than freeform prompt-writing.

The current mechanical direction is a **Cairn 2e-inspired dark-fantasy adaptation** layered over the existing deterministic oracle architecture:

- keep deterministic state, checkpoints, and validated mechanics outside the LLM
- keep the chat-first UX and AI-authored world generation
- add a more structured character/rules layer (stats, HP, inventory burden, item tags/effects) than the current fiction-only character sheet
- automatically backfill those Cairn-flavored mechanics from the already-authored character sheet instead of forcing the user to recreate the character

The app should therefore evolve from "oracle-only" into a hybrid: a deterministic oracle plus a lightweight but real rules chassis.

## Primary User Needs

- Private, self-directed play without needing to find a Discord group.
- A tone that is apolitical, traditional fantasy, and not driven by modern culture-war themes.
- Deterministic tracking for chaos factor, scenes, threads, NPCs, player notes, oracle outcomes, and now also a more structured character/rules layer.
- Clear separation between rules/state logic and creative prose generation.
- A UI engaging enough to make the project feel like a game, not just a prompt box.

## Non-Goals

- Do not build a Discord bot as the first version.
- Do not rely on an LLM to remember canonical state.
- Do not assume OSR is required unless later chosen explicitly.
- Do not import a heavyweight rules engine unless it clearly serves the personal play experience better than a lighter structured chassis like Cairn 2e.
- Do not copy proprietary oracle tables verbatim unless the user supplies licensed material or chooses an open alternative.
- Do not start by adapting another repository unless it is clearly simpler than building the base architecture directly.
- Do not change LLM provider or API signature unless explicitly requested.

## Source Material

The raw source note is preserved in `memory-bank/Trying to find a TTRPG community on Discord that i.md`. It records the full exploration from Discord community search to AI game master architecture.

## Workflow Rules (read this before touching git)

**This is a solo project.** The user's global rule says "Do not commit/push to main without my explicit approval, start a branch for new features/bugfixes" — but that rule has an explicit exception: it can be ignored when the project is definitively solo, evidenced by docs and/or commit history. **This project qualifies.** Evidence:

- Single-user FastAPI app bound to `127.0.0.1`, lives only on the user's machine and at most their personal GitHub (see `productContext.md` and `activeContext.md`).
- Commit history on `main` is exclusively the user / Cursor agent collaboration on this same project.
- The user has explicitly confirmed multiple times that the solo exception applies here.

**Therefore, on this repo:**

- Commit directly to `main`. Do **not** spin up `feature/*` branches at the start of a chat.
- Commit early and commit often — at minimum once per turn that produces real changes.
- Push to `origin/main` after each commit unless the user says otherwise.
- Do not ask "should I commit this?" — just commit it with a clear message and keep going.

If a future chat thread starts spawning a feature branch, that is a regression of this rule. Stop, re-read this section, and switch back to committing on `main`.
