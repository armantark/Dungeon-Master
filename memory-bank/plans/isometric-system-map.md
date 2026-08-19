# Isometric System Map Contract

Date: 2026-08-19
Driver: Codex on `main`

## Deliverable contract

- Canonical plan artifact: `memory-bank/status-updates/dungeon-master-system-map-plan-2026-08-19.html`.
- Canonical final artifact: `memory-bank/status-updates/dungeon-master-system-map-2026-08-19.html`.
- Format: one self-contained responsive HTML document with inline CSS and JavaScript, no runtime network calls, and no external assets.
- Visual model: an isometric grid with distinct 3D building silhouettes for the desktop shell, Svelte client, FastAPI edge, orchestration, deterministic mechanics, LLM workers, and persistence.
- Flow contract: every connector must name its real payload and direction; control, deterministic data, model inference, and persistence must use distinct visual encodings defined in the legend.
- Evidence contract: each building and explainer claim must cite a real repository file and line number from merged `main`.
- Interaction contract: selecting a building or flow updates an explainer panel; keyboard focus and reduced-motion behavior are required.
- Repository writes: the driver owns the contract, plan artifact, memory-bank updates, git, and verification. K3 owns only the final HTML frontend implementation after the driver supplies verified architecture evidence. Read-only analysis leaves own no files.

## Tree

### Leaf A: backend and state-path evidence

Owner: read-only Codex leaf.

Success criteria:

1. Identify the thin FastAPI entry points for bootstrap, ordinary turns, streaming turns, explicit mechanics, settings, and save lifecycle with file-and-line evidence.
2. Trace one ordinary natural-language turn from HTTP request through planning, deterministic execution, narration, post-narration continuity, persistence, and full-state return.
3. Separate deterministic Python components from LLM-backed structured workers and prose narration.
4. Name the concrete payloads that cross each backend boundary, including `GameState`, turn plans, oracle outcomes, NDJSON stage/content events, and persisted files.
5. Identify checkpoint, event-log, memory-sidecar, save-library, credential, and runtime-settings storage paths and ownership.
6. Report uncertain or conditional paths explicitly rather than inferring them.
7. CHECK: `rg -n "FastAPI|GameService|TurnRouter|NarrativeEngine|StateStore|StreamingResponse" src/dungeon_master`; EXPECT: every reported node is backed by at least one matching definition or call site.

### Leaf B: frontend, desktop, and delivery evidence

Owner: read-only Codex leaf.

Success criteria:

1. Trace browser-dev and packaged-desktop startup paths, including Vite proxying, Tauri sidecar spawn, runtime API-base discovery, and app-data path injection.
2. Trace a player submission from `Composer` through the Svelte store/API client to NDJSON stream consumption and whole-`GameState` replacement.
3. Identify which frontend surfaces consume mechanics, narration, stage progress, save-library state, settings, and credentials.
4. Identify build and release infrastructure with file-and-line evidence.
5. Name payloads at each frontend/desktop boundary and distinguish HTTP JSON from Tauri invoke and process environment.
6. Report conditional browser-versus-desktop branches explicitly.
7. CHECK: `rg -n "bootstrapRuntime|submit\(|stream|invoke|Command|proxy|sidecar" web/src web/src-tauri web/vite.config.ts scripts`; EXPECT: every reported node is backed by at least one matching definition or call site.

### Leaf C: K3 frontend implementation

Owner: Kimi K3, scoped to the final artifact only.

Success criteria:

1. Render the full verified system as an isometric campus with at least six visibly different building types, not a flat card diagram.
2. Show real control/data routes with directional traces and concise payload labels that remain legible at desktop and mobile widths.
3. Include a complete legend for node roles, route categories, and payload semantics.
4. Include a selectable explainer panel that maps each node/route to its responsibility, why the seam exists, and repository citations.
5. Preserve the project's dark grimoire/iron/gold identity while making the architecture data readable and avoiding decorative UI clichés.
6. Meet keyboard, focus, contrast, semantic-HTML, reduced-motion, and 400px-to-1400px responsive requirements.
7. Remain a single self-contained HTML file with no external dependencies or runtime network calls.
8. CHECK: `python3 /Users/ArmanTarkhanian1/.codex/skills/status-artifact/scripts/check_artifact.py memory-bank/status-updates/dungeon-master-system-map-2026-08-19.html`; EXPECT: `PASS` and no mechanical failures.

### Root integration

Owner: driver.

Success criteria:

1. Every local and remote-tracking branch is contained by `main` before analysis begins.
2. Architecture evidence from both read-only leaves is reconciled against current merged source; no uncited or stale path appears in the map.
3. The plan artifact remains unchanged after implementation begins.
4. The final map passes the artifact checker and manual browser inspection in Zen/PinchTab at desktop and mobile viewport sizes.
5. Repository-specific implementation and design decisions discovered during analysis are recorded in the memory bank.
6. All non-secret changes are committed atomically on `main`; no remote push occurs without an explicit request.
7. The learning checklist is created and the handoff ends by asking the user to restate the architecture before the first quiz question.
8. CHECK: `git branch --no-merged main && git branch -r --no-merged main`; EXPECT: no branch names.
9. CHECK: `git status --short`; EXPECT: no output after final commit.

## Event log

- 2026-08-19: Contract created after branch consolidation and initial repository orientation.
- 2026-08-19: Backend and frontend read-only evidence leaves completed and root reconciled their citations against merged `main`.
- 2026-08-19: K3 frontend implementation is blocked before file creation. Direct calls at `max`, `high`, and `low` effort each ended after three attempts with `error: provider request failed after 3 attempts: The read operation timed out`.
- 2026-08-19: The user authorized Opus as the replacement frontend implementer. Opus created the final atlas; root corrected evidence wording, passed the artifact checker, and verified all route and explainer interactions in PinchTab. Postplan hosting remains blocked on authentication because the interactive file contains inline JavaScript.

## Dev-route correction contract

The standalone artifact is now only a source/evidence prototype. The accepted product surface is a dev-only route in the existing Vite + Svelte application.

- Driver ownership: all implementation files, browser state, tests, git, and final verification.
- Read-only leaf ownership: route/dev-flag/test-convention discovery only; no files and no browser.
- Route contract: direct navigation must render the architecture map only when the Vite dev flag is enabled; normal game startup and production builds must not expose or bundle a discoverable product navigation entry.
- Visual contract: preserve the verified topology, payloads, citations, legend, and explainer, but rebuild malformed geometry as native Svelte/SVG components with explicit layer groups and stable depth keys.
- Integration contract: reuse the app's established typography, material palette, responsive conventions, and Vite environment typing rather than copying the standalone document shell.

### Read-only route-convention leaf

1. Identify how this non-SvelteKit app chooses its root component and whether any route/dev-flag convention already exists.
2. Identify the correct Vite environment flag naming and TypeScript declaration seam.
3. Identify the narrowest tests that can prove disabled, enabled, and normal-app behavior.
4. Identify local start commands and backend requirements for browser verification.
5. Cite every recommendation with a current file and line.
6. CHECK: `rg -n "import.meta.env|window.location|new App|mount\\(" web/src web/vite.config.ts`; EXPECT: a concrete integration seam with no guessed router dependency.

### Root correction criteria

1. A dev-flagged local URL opens the native architecture map without loading campaign state.
2. With the flag absent, that URL falls back to the normal application and exposes no architecture navigation.
3. Building geometry has no self-overlap or ambiguous front/back surfaces at desktop or mobile widths.
4. Frontend, transport seam, backend, and desktop/delivery are unmistakable before interaction.
5. Route selection, step tracing, building selection, source citations, keyboard focus, and reduced motion work.
6. Frontend unit, type, build, and browser checks pass.
7. Memory-bank architecture and delivery decisions are updated; all non-secret changes commit atomically on local `main` without a push.

### Correction event log

- 2026-08-19: User rejected the standalone-document delivery and clarified that the malformed 3D models, not only painter order, must be rebuilt behind a dev-only local app endpoint.
- 2026-08-19: Read-only route audit confirmed the app has no router and identified `web/src/main.ts` as the narrow mount seam. Driver implemented an exact-path Vite dev gate, native Svelte/SVG models, tests, and local documentation.
- 2026-08-19: The first production build proved a helper-mediated `import.meta.env.DEV` check still emitted the dynamic map chunk. Moving the dynamic import inside Vite's literal compile-time dev branch removed the chunk; a content scan of `dist/` is now green.
- 2026-08-19: Desktop/mobile browser smoke passed with no API requests. Startup switching, trace advancement, click selection, and keyboard selection all update the same explainer contract.
- 2026-08-19: The requested Opus review was attempted through the read-only Claude route but produced no output for ten minutes and was interrupted. Local type, test, production-exclusion, and browser evidence remain the acceptance authority.
