# Architecture map 3D repair

## Contract

The accepted endpoint remains `/__dev/architecture`, guarded by Vite development mode and `VITE_ENABLE_ARCHITECTURE_MAP=true`. `web/src/lib/dev-architecture.ts` remains the authority for nodes, roles, paths, payloads, and citations. The repair must restore varied isometric infrastructure, use a real 3D depth buffer, preserve the existing path controls and explainer, and reveal route segments progressively so connectors do not form an unreadable all-at-once overlay.

The root agent owns every repository edit, dependency change, browser session, test, and commit. Review leaves are read-only and own no files. No leaf may run git, install dependencies, edit files, start or stop shared servers, or operate the browser.

## Tree

### Leaf A: 3D implementation review

- Inspect the existing architecture-map components and dependencies.
- Compare the smallest credible Three.js integration against other installed/native options.
- Require real WebGL depth testing, an orthographic isometric camera, varied building silhouettes, readable HTML controls, reduced motion, and deterministic teardown.
- Identify concrete Svelte 5 lifecycle and testing risks.
- Return a bounded recommendation with exact affected files and no edits.
- CHECK: `rg -n "@xyflow/svelte|three|ArchitectureMap" web/package.json web/src/components/architecture`
- EXPECT: one minimal library recommendation plus a risk checklist.

### Leaf B: route and information-design review

- Inspect the authoritative path data and current route/tracing behavior.
- Explain exactly why connectors overlap in the current default state.
- Propose a progressive route visualization that still exposes every dependency and payload.
- Preserve explicit Frontend, Transport, Backend, Persistence, and Desktop & Delivery demarcation.
- Include desktop and 390-pixel mobile behavior plus keyboard and screen-reader semantics.
- Return an acceptance checklist and no edits.
- CHECK: `rg -n "traceIndex|flowEdges|ARCHITECTURE_PATHS|payload" web/src/components/architecture web/src/lib/dev-architecture.ts`
- EXPECT: one route-state model that never renders every payload label at once.

### Leaf C: full-state synchronization teaching review

- Trace the exact backend response and frontend replacement code for an ordinary turn.
- Separate what full-state replacement does from what Svelte rendering does afterward.
- Identify the concrete correctness benefits in this single-player local-sidecar architecture.
- Identify measured signals that would justify deltas, and a migration that preserves server authority.
- Return a principal-engineer-ready explanation grounded in exact files and no edits.
- CHECK: `rg -n "final_state|this.state =|GameState|state =" web/src/lib src/dungeon_master | head -n 160`
- EXPECT: a teach-first explanation that does not rely on unexplained jargon.

### Root integration criteria

- The live endpoint contains a WebGL canvas and no Svelte Flow graph.
- The scene contains all 15 authoritative nodes as varied 3D infrastructure on five visibly distinct territories.
- The browser initially renders no route spaghetti; Trace next step reveals one additional dependency and its payload at a time.
- Turn, Startup, Persistence, and Release tabs select the correct route and reset tracing deterministically.
- Node or step selection updates the source-backed explainer through mouse and keyboard controls.
- Desktop and 390 x 844 renders have no horizontal overflow and retain readable controls, step rail, legend, and explainer.
- Reduced-motion behavior disables camera/building animation without hiding content.
- `npm run check`, all frontend tests, and `npm run build` pass; the production bundle contains no architecture scene chunk.
- PinchTab verifies the original red signals become green and captures final desktop and mobile renders.
- One atomic commit records the repair; nothing is pushed.

## Event log

- 2026-08-20 16:08 PDT: Contract frozen after the user identified the flowchart substitution and overlapping connectors as requirement regressions.
- 2026-08-20 16:11 PDT: Browser baseline reproduced the exact regression with `canvas = 0` and `.svelte-flow__edge-path = 10` before tracing.
- 2026-08-20 16:14 PDT: Read-only reviews converged on plain Three.js, semantic HTML controls, five raised territories, zero initial connectors, and exactly one visible segment/payload at the trace cursor.
- 2026-08-20 16:37 PDT: Root verification is 9/10 with the final commit pending. `svelte-check` is 0/0, Vitest is 322/322, the production build excludes the architecture scene, HTTP is 200, the browser baseline is now `canvas = 1` and Svelte Flow edges `= 0`, single-segment tracing and path reset pass, keyboard selection passes, and 390 x 844 renders at `scrollWidth = 390`.
- 2026-08-20 16:39 PDT: Root integration is 10/10. Corrective commit `cbcd9d9` records the Three.js scene, route-state contract, tests, browser evidence, and memory-bank updates; nothing was pushed.
