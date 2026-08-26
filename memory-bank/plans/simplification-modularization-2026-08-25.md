# Simplification and modularization program

Date: 2026-08-25
Status: accepted for implementation
Driver: Codex root agent

## Goal

Reduce accidental complexity and split the four largest runtime files at proven seams. Preserve public imports, HTTP payloads, save compatibility, deterministic mechanics, and the full-state client contract.

## Module layout

The existing public modules remain facades during this program. New internal modules sit behind them.

```text
src/dungeon_master/
  application/
    continuity.py       # post-narration reconciliation
    turn_commit.py      # common canonical commit tail
  generation/
    character.py        # character templates, quiz, and draft generation
    world.py            # campaign world generation
    contracts.py        # generated-output and result types
  mechanics/
    inventory.py        # inventory transfer and derived loadout rules
  transport/
    stream_runtime.py   # session, cancellation, and NDJSON production

web/src/lib/
  store/
    stream-runner.ts    # progress reduction and terminal application
    save-binding.ts     # atomic save-state publication helpers
  contracts/
    encounter.ts        # canonical backend encounter wire shape
```

`campaign.py`, `cairn.py`, `service.py`, `api.py`, `store.svelte.ts`, and `types.ts` keep their current caller-facing imports until a later clean break is justified.

## Interface contract

- `GameService` remains the application facade used by FastAPI.
- `CairnEngine` remains the deterministic mechanics facade.
- `create_app(...)`, request paths, response schemas, and NDJSON event shapes do not change.
- `GameState` remains the canonical persisted and client-replacement payload.
- Save files and checkpoint formats do not change in this program.
- New internal modules return typed results. They do not write canonical state independently.
- Model IDs, provider call shapes, prompt behavior, and reasoning profiles do not change unless a confirmed simplification requires it.

## Ownership tree

### Wave 1A: Campaign generation

Owner files: `campaign.py`, new `generation/**`, `tests/test_campaign.py`.

Success criteria:

1. Campaign generation failure raises `CampaignGenerationError`; it never returns fabricated active canon.
2. Character and world generation implementations move behind `generation/` modules.
3. Existing `dungeon_master.generation` imports remain valid.
4. Character fallback behavior remains valid when no model is configured.
5. `CHECK: uv run pytest tests/test_campaign.py -q`; `EXPECT: all tests pass`.
6. `CHECK: uv run ruff check src/dungeon_master/generation/__init__.py src/dungeon_master/generation tests/test_campaign.py`; `EXPECT: All checks passed!`.
7. `CHECK: uv run mypy src/dungeon_master/generation/__init__.py src/dungeon_master/generation`; `EXPECT: Success: no issues found`.

### Wave 1B: Mechanics inventory ownership

Owner files: `cairn.py`, new `mechanics/**`, `tests/test_cairn.py`.

Success criteria:

1. `CairnEngine` owns item transfer and complete derived-state repair.
2. A transfer resolves canonical actors once by stable actor id.
3. Transfer clears invalid equipped and primary-weapon state.
4. Transfer recomputes armor, burden, survival flags, and terminal character state for both actors.
5. Existing Cairn public imports remain valid.
6. `CHECK: uv run pytest tests/test_cairn.py -q`; `EXPECT: all tests pass`.
7. `CHECK: uv run ruff check src/dungeon_master/mechanics/engine.py src/dungeon_master/mechanics tests/test_cairn.py`; `EXPECT: All checks passed!`.
8. `CHECK: uv run mypy src/dungeon_master/mechanics/engine.py src/dungeon_master/mechanics`; `EXPECT: Success: no issues found`.

### Wave 1C: Frontend state and stream ownership

Owner files: `web/src/lib/store.svelte.ts`, `streaming.ts`, `types.ts`, `combat.ts`, `history.ts`, `ChatFeed.svelte`, related tests, new `web/src/lib/store/**` and `contracts/**`, dead `ChaosDial.svelte`, and the legacy texture action use.

Success criteria:

1. `consumeStream` returns terminal events but does not dispatch terminal callbacks.
2. The store applies each terminal event once.
3. Save selection publishes the save id and fetched state together.
4. `GameState` includes the canonical encounter wire shape.
5. Combat keeps a derived view model but removes duplicate backend wire interfaces and unsafe casts.
6. Chat uses the existing shared transcript derivation.
7. Unused chaos and texture code is deleted.
8. `CHECK: cd web && npm run check`; `EXPECT: 0 errors and 0 warnings`.
9. `CHECK: cd web && npm test -- --run`; `EXPECT: all tests pass`.

### Driver: Continuity and service seam

Owner files: `service.py`, new `application/continuity.py`, continuity tests, and integration edits after Wave 1B.

Success criteria:

1. All direct and natural turn callers use post-narration continuity.
2. The obsolete pre-narration classifier path and flags are deleted.
3. Final narration is required for continuity update prompts.
4. Inventory transfer delegates to `CairnEngine`.
5. `GameService` remains the external application interface.
6. Focused service and continuity tests pass.
7. Ruff and mypy pass for touched backend modules.

## Wave 2

Start Wave 2 only after Wave 1 and the driver integration pass are green.

1. Move cancellation ownership into `SessionRegistry` and extract `transport/stream_runtime.py`.
2. Extract the common post-narration commit tail into `application/turn_commit.py`.
3. Remove legacy `RoutedTurn` conversions and duplicate coordinated-attack identity.
4. Split test-only construction helpers after production seams settle.
5. Apply the small architecture-map, version, documentation, and baseline-generator cleanup.

## Verification gate

Run this gate after each wave:

```shell
uv run ruff check src tests
uv run mypy src tests
uv run pytest -q
cd web
npm run check
npm test -- --run
npm run build
```

The verifier must inspect the full diff, public imports, package layout, and repository status. The verifier must reject pass-through modules that only move code without reducing an interface or centralizing ownership.

## Event log

- 2026-08-25: The driver froze the interface contract and file ownership before fanout.
