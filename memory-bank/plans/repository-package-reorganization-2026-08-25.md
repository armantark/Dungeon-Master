# Repository package reorganization contract

## Goal

Make the repository easy to navigate by responsibility. Reduce the remaining god files without changing product behavior or public contracts.

## Frozen interfaces

- Keep these Python imports valid: `dungeon_master.api`, `dungeon_master.cairn`, `dungeon_master.memory`, `dungeon_master.narrative`, `dungeon_master.service`, and `dungeon_master.turn_router`.
- Keep `GameService`, `CairnEngine`, `MemoryManager`, `NarrativeEngine`, `TurnRouter`, and `create_app` as the external interfaces.
- Keep CLI entry points, HTTP paths, request and response payloads, save files, checkpoints, stream events, and OpenAPI output compatible.
- Keep `web/src/lib/store.svelte.ts` and `web/src/lib/types.ts` as stable frontend import surfaces.
- Do not change the configured model ids, model call signatures, game rules, prompts, or UI behavior.

## Target layout

```text
src/dungeon_master/
├── application/
│   ├── setup/
│   ├── turns/
│   ├── regeneration/
│   └── maintenance/
├── domain/
├── mechanics/
├── memory/
├── llm/
│   ├── completion/
│   ├── narration/
│   └── planning/
└── transport/http/

web/src/
├── contracts/
├── features/
│   ├── combat/
│   ├── inspector/
│   ├── play/
│   ├── saves/
│   ├── settings/
│   └── setup/
└── state/
```

The implementation can use fewer folders when a proposed folder would contain only a pass-through file. The responsibility names are binding; the exact internal file count is not.

## Ownership tree

### Leaf A: deterministic mechanics

Owns:

- `src/dungeon_master/cairn.py`
- `src/dungeon_master/mechanics/**`
- `tests/test_cairn.py`

Criteria:

1. Split combat, inventory/item, survival/resource, and generation support into named mechanics modules.
2. Keep `CairnEngine` and all current imports compatible.
3. Do not move canonical Pydantic wire models out of `models.py` in this leaf.
4. Remove the broad `cairn.py` Ruff exception or reduce it to narrow file-specific exceptions.
5. `CHECK: uv run pytest tests/test_cairn.py -q`; `EXPECT: exit 0`.
6. `CHECK: uv run ruff check` on owned files; `EXPECT: All checks passed!`.
7. `CHECK: uv run mypy` on owned files; `EXPECT: Success: no issues found`.

### Leaf B: model and memory infrastructure

Owns:

- `src/dungeon_master/memory.py`
- `src/dungeon_master/narrative.py`
- `src/dungeon_master/turn_router.py`
- new `src/dungeon_master/memory/**` and `src/dungeon_master/llm/**`
- `tests/test_memory.py`, `tests/test_narrative.py`, and `tests/test_turn_router.py`

Criteria:

1. Separate memory contracts, projection, retrieval, and rendering.
2. Separate provider completion transport from narration prompt assembly.
3. Separate planning contracts, prompts, review gates, and normalization.
4. Keep the three root modules as compatibility facades.
5. Keep public classes, enums, helper imports, prompts, and behavior compatible.
6. `CHECK: uv run pytest tests/test_memory.py tests/test_narrative.py tests/test_turn_router.py -q`; `EXPECT: exit 0`.
7. `CHECK: uv run ruff check` on owned files; `EXPECT: All checks passed!`.
8. `CHECK: uv run mypy` on owned files; `EXPECT: Success: no issues found`.

### Leaf C: frontend features and state

Owns:

- `web/src/**`
- excludes `web/package.json`, lock files, and lint configuration

Criteria:

1. Move UI modules into feature folders by user-facing responsibility.
2. Extract Inspector sections into focused Svelte components.
3. Split store implementation into runtime, save, play, and stream responsibilities while preserving one canonical state owner.
4. Split TypeScript contracts by domain and re-export them through `lib/types.ts`.
5. Keep the UI, routes, state replacement, and imports compatible.
6. `CHECK: npm run check`; `EXPECT: svelte-check found 0 errors and 0 warnings`.
7. `CHECK: npm test -- --run`; `EXPECT: all tests pass`.
8. `CHECK: npm run build`; `EXPECT: built successfully`.

### Driver: application, HTTP, lint, and integration

Owns:

- `src/dungeon_master/service.py`
- `src/dungeon_master/api.py`
- new application and HTTP packages not owned by other leaves
- `tests/test_service.py`, `tests/test_api.py`
- `pyproject.toml`
- `web/package.json`, lock files, ESLint, and Prettier configuration
- repository documentation and memory bank

Criteria:

1. Split application use cases from `GameService` by setup, direct mechanics, turns, regeneration, and maintenance.
2. Split HTTP schemas, dependencies/runtime wiring, and route groups from `api.py`.
3. Keep `GameService` and `create_app` as stable facades.
4. Configure Ruff formatting and full lint, strict mypy, type-aware ESLint, Svelte lint, and Prettier.
5. Apply formatting once, then make all checks read-only gates.
6. Run the full backend and frontend test suites.
7. Do a live isolated browser smoke for save selection and one deterministic action.
8. Complete a deletion-focused independent review before the final commit.

## Integration stop conditions

- Stop if a move requires a wire, save, or public import break.
- Stop if a new module only mirrors one function without hiding responsibility.
- Do not merge a leaf until its checks pass and the driver verifies its public facade.
- Do not push any commit.

## Event log

- 2026-08-25: Contract frozen before fanout.
- 2026-08-25: Driver installed the Python and TypeScript standards gates and split HTTP schemas, runtime wiring, and turn-stage timing into focused modules.
- 2026-08-25: Mechanics closed with four domain modules and a 63-line compatibility facade; model and memory infrastructure closed with separate memory, completion, narration, and planning owners.
- 2026-08-25: Second fanout wave started for application use cases and HTTP route groups.
- 2026-08-25: Application mixins were rejected as a false seam. Typed plan execution now uses a composed executor with explicit service ports, while cross-cutting lifecycle and persistence work stays in `GameService`.
- 2026-08-25: Frontend state extraction completed with `GameStore` as the sole rune-backed owner and explicit play, save, runtime, and stream workflows.
- 2026-08-25: Full verification passed: Ruff format/lint, strict mypy, 341 backend tests, Prettier, type-aware ESLint, zero Svelte diagnostics, 338 frontend tests, a 217-module production build, and an npm audit with zero findings.
- 2026-08-25: Independent deletion review returned no must-fix items. Results are recorded in `memory-bank/status-updates/repository-package-reorganization-results-2026-08-25.html`.
