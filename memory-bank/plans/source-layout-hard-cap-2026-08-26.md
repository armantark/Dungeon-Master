# Source layout and line-cap contract

Date: 2026-08-26
Status: accepted for implementation
Driver: Codex root agent

## Goal

Make source ownership obvious from paths. Keep every hand-written source and test file below 1,000 physical lines. Keep only conventional package files at the root of `src/dungeon_master/`.

## Frozen behavior

- Do not change HTTP paths, OpenAPI shapes, NDJSON events, save/checkpoint formats, mechanics, prompts, model configuration, or UI behavior.
- Keep public classes and functions available from their new owning packages.
- Update all repository imports, CLI entry points, documentation, architecture citations, and tests in the same change.
- Do not add compatibility files back to `src/dungeon_master/`; the explicit layout request supersedes old root-module import paths.
- Do not create, open, or host status artifacts during this task.

## Enforced invariants

1. Every tracked hand-written `.py`, `.ts`, `.svelte`, `.css`, and `.rs` source or test file has at most 999 physical lines.
2. `src/dungeon_master/` contains only `__init__.py` and conventional package metadata such as `py.typed` if added later.
3. A repository check fails loudly when either invariant regresses.
4. Splits follow cohesive responsibilities. No one-function pass-through modules or facade-only files are added to satisfy the count.

## Target backend layout

```text
src/dungeon_master/
├── __init__.py
├── application/      # orchestration, updates, cancellation, OOC explanation
├── config/           # runtime settings and credentials
├── domain/           # canonical Pydantic state and event contracts
├── entrypoints/      # server, backfill, and fixture CLIs
├── generation/       # campaign and character generation
├── infrastructure/   # observability
├── llm/              # completion, planning, narration, shared prompts
├── mechanics/        # Cairn and oracle rules
├── memory/           # derived-context projection and retrieval
├── persistence/      # state store and save library
└── transport/http/   # FastAPI assembly and routes
```

## Ownership tree

### Leaf A: application source

Owns `src/dungeon_master/application/game_service.py`, `src/dungeon_master/application/**`, and new application workflow modules only.

Criteria:

1. Reduce `service.py` below 1,000 lines through composed deep modules, not mixins or `self: GameService` helpers.
2. Keep `GameService` as the single application interface used by HTTP callers.
3. Keep campaign lifecycle, persistence ordering, cancellation, and commit semantics unchanged.
4. Keep every owned file below 1,000 lines.
5. `CHECK: uv run pytest tests/test_service.py tests/test_api.py -q`; `EXPECT: exit 0` before test files move.
6. `CHECK: uv run ruff check` and strict mypy on owned source; `EXPECT: clean`.

### Leaf B: mechanics and generation source

Owns `src/dungeon_master/mechanics/**` and `src/dungeon_master/generation/**` only.

Criteria:

1. Split combat, mechanics-generation, and character-generation implementations at cohesive rule/generation seams.
2. Preserve the `CairnEngine` and campaign-generation interfaces and deterministic behavior.
3. Keep every owned file below 1,000 lines.
4. Do not change prompts, model ids, schema fields, or rules.
5. `CHECK: uv run pytest tests/test_cairn.py tests/test_campaign.py -q`; `EXPECT: exit 0` before test files move.
6. `CHECK: uv run ruff check` and strict mypy on owned source; `EXPECT: clean`.

### Leaf C: tests and frontend stylesheet

Owns `tests/test_service.py`, `tests/test_api.py`, `tests/test_cairn.py`, `tests/test_turn_router.py`, new test packages/helpers, `web/src/styles/app.css`, and new CSS files under `web/src/styles/` only.

Criteria:

1. Split large tests by behavior area with shared fixtures in conventional `conftest.py` or helper modules.
2. Split `app.css` by stable visual responsibility while preserving cascade order and rendered behavior.
3. Keep every owned file below 1,000 lines.
4. Preserve test collection count and assertions.
5. `CHECK: uv run pytest`; `EXPECT: all backend tests pass`.
6. `CHECK: npm run format:check && npm run lint && npm run check && npm run test -- --maxWorkers=1 && npm run build`; `EXPECT: clean`.

### Driver: package migration and enforcement

Owns all remaining root modules, import rewrites, CLI configuration, CI, README, memory bank, and final integration.

Criteria:

1. Move every non-conventional root module into the target ownership package.
2. Leave only `src/dungeon_master/__init__.py` at package root.
3. Add one deterministic source-layout checker and run it in CI.
4. Repair every repository import and source citation.
5. Verify the full Python and frontend gates after integration.
6. Run an independent deletion-focused review over the final diff.
7. Commit atomically on local `main`; do not push without a new explicit request.

## Event log

- 2026-08-26: Baseline inventory found nine files above the cap and 22 non-conventional modules at `src/dungeon_master/` root.
- 2026-08-26: Contract frozen. Status artifacts are explicitly disabled for this task.
- 2026-08-26: Oversized application, mechanics, generation, test, and stylesheet files were split at responsibility boundaries; every owned source file is now below the cap.
- 2026-08-26: All 22 root implementation modules moved into `application`, `config`, `domain`, `entrypoints`, `generation`, `infrastructure`, `llm`, `mechanics`, `persistence`, or `transport`; only `src/dungeon_master/__init__.py` remains at package root.
- 2026-08-26: Imports, console entry points, README ownership guidance, current memory-bank guidance, and the development architecture-map citations were migrated to the final paths.
- 2026-08-26: Independent deletion-focused review found and removed internal `ApplicationState` pass-through methods, widened the checker from selected source roots to all repository source, and corrected the last current-state facade references. The review passed on recheck.
- 2026-08-26: Final deterministic verification passed: Ruff format/lint, repository source-layout checker, strict mypy, 338 backend tests excluding the live model judge, all three CLI help commands, Prettier, ESLint, Svelte diagnostics, 338 frontend tests, production build, and npm audit with zero findings. The unchanged live DeepEval attack case failed twice because generated prose left the goblin alive while the judge inferred death from `Success`; the exact scores and rationale are recorded in `papercuts.md`.
