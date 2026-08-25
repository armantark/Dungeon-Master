export type SystemRole =
  | "client"
  | "python"
  | "structured"
  | "prose"
  | "persist"
  | "desktop";

export type BuildingKind =
  | "gatehouse"
  | "relay"
  | "depot"
  | "foundry"
  | "cistern"
  | "observatory"
  | "tower"
  | "theater"
  | "loom"
  | "vault"
  | "library"
  | "homes"
  | "shell"
  | "works"
  | "crane";

export interface SourceCitation {
  file: string;
  line: number;
}

export interface ArchitectureNode {
  id: string;
  name: string;
  kind: BuildingKind;
  role: SystemRole;
  x: number;
  y: number;
  width: number;
  depth: number;
  height: number;
  responsibility: string;
  input: string;
  output: string;
  rationale: string;
  citations: SourceCitation[];
}

export interface PathStep {
  node: string;
  payload?: string;
  detail?: string;
}

export interface ArchitecturePath {
  id: "turn" | "startup" | "persistence" | "release";
  name: string;
  summary: string;
  steps: PathStep[];
}

export interface ArchitectureRouteSegment {
  from: PathStep;
  to: PathStep;
}

export const ROLE_META: Record<SystemRole, { label: string; color: string }> = {
  client: { label: "Browser client · TypeScript", color: "#3f8b91" },
  python: { label: "Deterministic Python", color: "#68788f" },
  structured: { label: "Structured model call", color: "#8365b7" },
  prose: { label: "Prose model call", color: "#b96748" },
  persist: { label: "Persistence", color: "#a88434" },
  desktop: { label: "Desktop shell & delivery", color: "#557c5e" },
};

export const ARCHITECTURE_NODES: ArchitectureNode[] = [
  {
    id: "composer", name: "Composer Gatehouse", kind: "gatehouse", role: "client",
    x: 118, y: 300, width: 2, depth: 2, height: 60,
    responsibility: "The player-facing entrance. It forwards ordinary free text to the store while slash commands use an explicit client dispatch path.",
    input: "Player free text", output: "POST body { text }",
    rationale: "The browser does not guess intent, targets, or dice outcomes. Natural-language mechanics can evolve without shipping a new UI parser.",
    citations: [{ file: "web/src/components/Composer.svelte", line: 75 }],
  },
  {
    id: "relay", name: "Relay Post", kind: "relay", role: "client",
    x: 244, y: 230, width: 1.8, depth: 1.8, height: 48,
    responsibility: "Resolves the API base for browser or desktop, opens the streaming request, and hands the response body to the frame reader.",
    input: "{ text } + resolved API base", output: "POST /api/turn/stream · open NDJSON body",
    rationale: "Browser and desktop share one transport. Only the runtime base URL changes.",
    citations: [{ file: "web/src/lib/api.ts", line: 376 }, { file: "web/src/lib/desktop.ts", line: 12 }],
  },
  {
    id: "depot", name: "Stream Depot", kind: "depot", role: "python",
    x: 405, y: 178, width: 3, depth: 1.8, height: 44,
    responsibility: "FastAPI entry point plus the detached stream runtime. It accepts a request while one registry owns cancellation, replay, and response frames.",
    input: "POST /api/turn/stream { text }", output: "meta · stage · thinking_delta · content_delta · final_state · error",
    rationale: "One session object owns the wire vocabulary, replay, and live-tail behavior.",
    citations: [{ file: "src/dungeon_master/api.py", line: 839 }, { file: "src/dungeon_master/transport/stream_runtime.py", line: 140 }],
  },
  {
    id: "foundry", name: "Turn Foundry", kind: "foundry", role: "python",
    x: 545, y: 238, width: 2.4, depth: 2.4, height: 72,
    responsibility: "The deterministic service orchestrator. It drives state loading, planning, rules, narration, continuity, and commit in one ordered pipeline.",
    input: "Turn text · active save · derived recall", output: "Stage events + one new GameState",
    rationale: "Turn order lives in Python rather than being distributed across model calls.",
    citations: [{ file: "src/dungeon_master/service.py", line: 1513 }, { file: "src/dungeon_master/service.py", line: 1680 }],
  },
  {
    id: "memory", name: "Memory Cistern", kind: "cistern", role: "python",
    x: 410, y: 314, width: 1.8, depth: 1.8, height: 38,
    responsibility: "Rebuildable recall derived from committed events and canonical state.",
    input: "events.jsonl + canonical GameState", output: "memory.json + prompt-ready recall",
    rationale: "A bad summary can degrade one turn, but it cannot corrupt canon because the sidecar is disposable.",
    citations: [{ file: "src/dungeon_master/memory.py", line: 335 }, { file: "src/dungeon_master/service.py", line: 3013 }],
  },
  {
    id: "router", name: "Router Observatory", kind: "observatory", role: "structured",
    x: 690, y: 195, width: 2, depth: 2, height: 80,
    responsibility: "The first model step. It returns a schema-validated TurnPlan describing the turn and its bounded operations.",
    input: "Turn text + state summary + recall", output: "Validated TurnPlan",
    rationale: "Downstream code branches on typed fields, never on model prose.",
    citations: [{ file: "src/dungeon_master/turn_router.py", line: 460 }, { file: "src/dungeon_master/service.py", line: 3013 }],
  },
  {
    id: "oracle", name: "Oracle Tower & Cairn Hall", kind: "tower", role: "python",
    x: 862, y: 238, width: 1.4, depth: 1.4, height: 116,
    responsibility: "Deterministic uncertainty and rules resolution. Dice and Cairn consequences are settled before prose begins.",
    input: "TurnPlan + canonical state", output: "Rolled outcome + rule effects",
    rationale: "The model may describe success or failure, but Python decides which occurred.",
    citations: [{ file: "src/dungeon_master/oracle.py", line: 30 }, { file: "src/dungeon_master/cairn.py", line: 707 }, { file: "src/dungeon_master/service.py", line: 1838 }],
  },
  {
    id: "narrative", name: "Narrative Theater", kind: "theater", role: "prose",
    x: 700, y: 318, width: 2.8, depth: 2.4, height: 54,
    responsibility: "The prose model streams a scene that is grounded in a resolved mechanical outcome.",
    input: "TurnPlan + resolved outcome + recall", output: "thinking_delta + content_delta",
    rationale: "Narration can interpret an outcome but cannot invent or mutate it.",
    citations: [{ file: "src/dungeon_master/narrative.py", line: 210 }, { file: "src/dungeon_master/service.py", line: 2936 }],
  },
  {
    id: "loom", name: "Thread & NPC Loom", kind: "loom", role: "structured",
    x: 872, y: 362, width: 2, depth: 2, height: 48,
    responsibility: "Post-prose structured workers propose durable thread, NPC, inventory, and character-effect changes implied by the scene.",
    input: "Final prose + existing canon", output: "Validated update proposals",
    rationale: "Continuity is reconciled from the exact prose the player saw, not from a pre-prose guess.",
    citations: [{ file: "src/dungeon_master/application/turn_commit.py", line: 53 }, { file: "src/dungeon_master/application/continuity.py", line: 67 }],
  },
  {
    id: "vault", name: "Archive Vault", kind: "vault", role: "persist",
    x: 585, y: 382, width: 2.4, depth: 2.4, height: 58,
    responsibility: "Atomic persistence for canonical state, append-only events, ordinary checkpoints, and turn checkpoints.",
    input: "New GameState + turn events", output: "game_state.json · events.jsonl · checkpoints/ · turn-checkpoints/",
    rationale: "A partial turn cannot replace the previous valid save, and a bad narration can be regenerated from its named checkpoint.",
    citations: [{ file: "src/dungeon_master/state_store.py", line: 44 }, { file: "src/dungeon_master/service.py", line: 3165 }],
  },
  {
    id: "library", name: "Save Library", kind: "library", role: "persist",
    x: 700, y: 444, width: 2, depth: 2, height: 42,
    responsibility: "Resolves the global library manifest into the active per-save directory and its metadata.",
    input: "library.json", output: "Active save path + save metadata",
    rationale: "Save selection stays outside the turn protocol, while settings and credentials remain app-global.",
    citations: [{ file: "src/dungeon_master/save_library.py", line: 44 }],
  },
  {
    id: "homes", name: "Client State District", kind: "homes", role: "client",
    x: 265, y: 374, width: 2.4, depth: 2.2, height: 34,
    responsibility: "Reads NDJSON frames, renders provisional deltas, then replaces the client store with the final full GameState.",
    input: "NDJSON frames", output: "Rendered scene + replaced GameState",
    rationale: "Wholesale replacement prevents client-side merge rules from drifting from server authority.",
    citations: [{ file: "web/src/lib/streaming.ts", line: 107 }, { file: "web/src/lib/store/stream-runner.ts", line: 61 }, { file: "web/src/lib/store.svelte.ts", line: 1483 }],
  },
  {
    id: "shell", name: "Tauri Shell & Vite Proxy", kind: "shell", role: "desktop",
    x: 245, y: 444, width: 2, depth: 2, height: 48,
    responsibility: "Hosts the UI. Dev uses the Vite proxy; packaged desktop spawns the sidecar, injects app-data paths, and publishes desktop_api_base.",
    input: "App-data path + stored credentials", output: "desktop_api_base + sidecar environment",
    rationale: "An ephemeral loopback port avoids collisions and keeps the API local to the player's machine.",
    citations: [{ file: "web/src-tauri/src/lib.rs", line: 36 }, { file: "web/vite.config.ts", line: 11 }, { file: "web/src/lib/desktop.ts", line: 12 }],
  },
  {
    id: "sidecar", name: "Sidecar Works", kind: "works", role: "desktop",
    x: 395, y: 494, width: 2, depth: 2, height: 52,
    responsibility: "Freezes the Python service into the one-file executable Tauri embeds.",
    input: "Python service tree", output: "Target-triple sidecar executable",
    rationale: "Players do not need a separate Python installation.",
    citations: [{ file: "scripts/build_tauri_sidecar.py", line: 32 }],
  },
  {
    id: "crane", name: "Release Crane", kind: "crane", role: "desktop",
    x: 520, y: 530, width: 1.6, depth: 1.6, height: 100,
    responsibility: "Runs checks, builds the sidecar, bundles Tauri, and creates the desktop release from one tagged commit.",
    input: "desktop-v* tag or manual dispatch", output: "Platform bundle + GitHub release",
    rationale: "The shipped binary is built from the same source revision that passed verification.",
    citations: [{ file: ".github/workflows/desktop-release.yml", line: 79 }],
  },
];

export const ARCHITECTURE_PATHS: ArchitecturePath[] = [
  {
    id: "turn", name: "Turn", summary: "One player sentence becomes one authoritative replacement GameState.",
    steps: [
      { node: "composer" },
      { node: "relay", payload: "{ text }", detail: "Ordinary prose leaves the composer untouched; the browser does not infer mechanics." },
      { node: "depot", payload: "POST /api/turn/stream", detail: "A detached session starts the turn and exposes replayable newline-delimited JSON." },
      { node: "foundry", payload: "turn generator", detail: "The service yields ordered progress while the transport session survives disconnects." },
      { node: "memory", payload: "canonical state + recall", detail: "The service loads source-of-truth state before using rebuildable recall." },
      { node: "router", payload: "bounded context", detail: "The router sees a state summary and recall, not the whole save directory." },
      { node: "oracle", payload: "TurnPlan", detail: "Python resolves typed operations, chance, and Cairn consequences." },
      { node: "narrative", payload: "resolved outcome", detail: "The prose model narrates a result already decided by code." },
      { node: "loom", payload: "final prose", detail: "Structured workers reconcile durable facts from committed narration." },
      { node: "vault", payload: "state + events", detail: "The new state, events, and checkpoints land atomically." },
      { node: "homes", payload: "final_state", detail: "The final frame replaces the entire Svelte store state." },
    ],
  },
  {
    id: "startup", name: "Startup", summary: "How the UI discovers a FastAPI service whose port may not exist until launch.",
    steps: [
      { node: "shell" },
      { node: "sidecar", payload: "port · paths · credentials" },
      { node: "depot", payload: "sidecar boots FastAPI" },
      { node: "relay", payload: "desktop_api_base" },
      { node: "library", payload: "settings · credentials · library" },
      { node: "homes", payload: "GameState" },
    ],
  },
  {
    id: "persistence", name: "Persistence", summary: "What is canonical on disk and what can be rebuilt.",
    steps: [
      { node: "foundry" },
      { node: "library", payload: "active save id" },
      { node: "vault", payload: "saves/<id>/" },
      { node: "memory", payload: "derived memory.json" },
    ],
  },
  {
    id: "release", name: "Release", summary: "From a verified tag to an installable desktop bundle.",
    steps: [
      { node: "crane" },
      { node: "sidecar", payload: "checks → PyInstaller" },
      { node: "shell", payload: "Tauri bundle → release" },
    ],
  },
];

export function nodeById(id: string): ArchitectureNode | undefined {
  return ARCHITECTURE_NODES.find((node) => node.id === id);
}

export function routeSegmentAt(
  path: ArchitecturePath,
  cursor: number,
): ArchitectureRouteSegment | undefined {
  if (cursor < 1 || cursor >= path.steps.length) return undefined;
  const from = path.steps[cursor - 1];
  const to = path.steps[cursor];
  return from && to ? { from, to } : undefined;
}
