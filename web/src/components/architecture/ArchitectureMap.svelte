<script lang="ts">
  import ArchitectureScene from "./ArchitectureScene.svelte";
  import {
    ARCHITECTURE_NODES,
    ARCHITECTURE_PATHS,
    ROLE_META,
    nodeById,
    type ArchitectureNode,
    type ArchitecturePath,
    type PathStep,
  } from "../../lib/dev-architecture";

  const repositoryBase = "https://github.com/armantark/Dungeon-Master/blob/main/";
  const BOUNDARIES = [
    { label: "Frontend", detail: "Svelte + TypeScript", color: "#3f8b91" },
    { label: "Transport", detail: "HTTP + NDJSON", color: "#b88a31" },
    { label: "Backend", detail: "FastAPI + Python + models", color: "#68788f" },
    { label: "Persistence", detail: "Canonical saves", color: "#a88434" },
    { label: "Desktop & Delivery", detail: "Tauri + sidecar + release", color: "#557c5e" },
  ] as const;
  const defaultPath: ArchitecturePath = ARCHITECTURE_PATHS[0]!;
  const defaultNode: ArchitectureNode = ARCHITECTURE_NODES[0]!;

  let activePathId = $state<ArchitecturePath["id"]>("turn");
  let selectedNodeId = $state(defaultPath.steps[0]?.node ?? defaultNode.id);
  let traceIndex = $state(-1);

  const activePath = $derived(
    ARCHITECTURE_PATHS.find((path) => path.id === activePathId) ?? defaultPath,
  );
  const selectedNode = $derived(nodeById(selectedNodeId) ?? defaultNode);
  const selectedStep = $derived(
    activePath.steps.find((step) => step.node === selectedNodeId),
  );
  const traceComplete = $derived(traceIndex === activePath.steps.length - 1);

  function choosePath(id: ArchitecturePath["id"]): void {
    const path = ARCHITECTURE_PATHS.find((candidate) => candidate.id === id) ?? defaultPath;
    activePathId = path.id;
    traceIndex = -1;
    selectedNodeId = path.steps[0]?.node ?? defaultNode.id;
  }

  function chooseNode(id: string): void {
    selectedNodeId = id;
  }

  function chooseStep(step: PathStep, index: number): void {
    selectedNodeId = step.node;
    traceIndex = index;
  }

  function traceNext(): void {
    traceIndex = traceComplete ? 0 : traceIndex + 1;
    selectedNodeId = activePath.steps[traceIndex]?.node ?? activePath.steps[0]?.node ?? defaultNode.id;
  }

  function resetTrace(): void {
    traceIndex = -1;
    selectedNodeId = activePath.steps[0]?.node ?? defaultNode.id;
  }
</script>

<section class="atlas" aria-labelledby="architecture-title">
  <header class="atlas__header">
    <div>
      <p class="kicker pixel">Dev architecture endpoint</p>
      <h1 id="architecture-title">Dungeon Master isometric system map</h1>
      <p class="lede">
        A depth-tested infrastructure campus showing the real control and data paths from the
        Svelte composer through deterministic Python, bounded model calls, atomic persistence,
        and the final client state.
      </p>
    </div>
    <p class="stamp pixel">source reconciled on local main</p>
  </header>

  <div class="atlas__layout">
    <div class="atlas__canvas iron">
      <div class="toolbar">
        <div class="path-tabs" role="group" aria-label="Choose an architecture path">
          {#each ARCHITECTURE_PATHS as path}
            <button
              type="button"
              class:active={path.id === activePath.id}
              aria-pressed={path.id === activePath.id}
              onclick={() => choosePath(path.id)}
            >
              {path.name}
            </button>
          {/each}
        </div>
        <span class="toolbar__spacer"></span>
        <button type="button" onclick={traceNext}>
          {traceComplete ? "Restart trace" : "Trace next step"}
        </button>
        <button type="button" class="ghost" onclick={resetTrace}>Reset</button>
      </div>

      <p class="path-summary">{activePath.summary}</p>

      <div class="boundary-strip" aria-label="Architecture territories">
        {#each BOUNDARIES as boundary}
          <span style={`--boundary:${boundary.color}`}>
            <strong>{boundary.label}</strong>
            <small>{boundary.detail}</small>
          </span>
        {/each}
      </div>

      <ArchitectureScene
        {activePath}
        {selectedNodeId}
        {traceIndex}
        onSelect={chooseNode}
      />

      <ol class="step-rail" aria-label={`${activePath.name} path steps`}>
        {#each activePath.steps as step, index}
          {@const node = nodeById(step.node)}
          {#if node}
            <li>
              <button
                type="button"
                class:active={node.id === selectedNode.id}
                class:current={traceIndex === index}
                aria-current={traceIndex === index ? "step" : undefined}
                onclick={() => chooseStep(step, index)}
              >
                <span class="step-rail__number pixel">{index + 1}</span>
                <span>{node.name}</span>
                {#if traceIndex === index && step.payload}<code>{step.payload}</code>{/if}
              </button>
            </li>
          {/if}
        {/each}
      </ol>

      <div class="legend" aria-label="Architecture role legend">
        {#each Object.values(ROLE_META) as meta}
          <span><i style={`--swatch: ${meta.color}`}></i>{meta.label}</span>
        {/each}
        <span><i class="legend__route"></i>Current dependency</span>
      </div>

      <details class="node-index">
        <summary>All infrastructure</summary>
        <div>
          {#each ARCHITECTURE_NODES as node}
            <button
              type="button"
              class:active={selectedNode.id === node.id}
              aria-pressed={selectedNode.id === node.id}
              onclick={() => chooseNode(node.id)}
            >
              <span>{node.name}</span>
              <small>{ROLE_META[node.role].label}</small>
            </button>
          {/each}
        </div>
      </details>
    </div>

    <aside class="explainer parchment deckle" aria-live="polite">
      <p class="explainer__path pixel">{activePath.name} path · {activePath.steps.length} stops</p>
      <h2>{selectedNode.name}</h2>
      <p class="explainer__role">{ROLE_META[selectedNode.role].label}</p>
      <p class="explainer__summary">{selectedNode.responsibility}</p>

      <dl>
        <div><dt>Receives</dt><dd>{selectedNode.input}</dd></div>
        <div><dt>Produces</dt><dd>{selectedNode.output}</dd></div>
      </dl>

      <section>
        <h3>Why this boundary exists</h3>
        <p>{selectedNode.rationale}</p>
      </section>

      {#if selectedStep?.detail}
        <section class="selected-edge">
          <h3>Selected route step</h3>
          <p>{selectedStep.detail}</p>
          {#if selectedStep.payload}<code>{selectedStep.payload}</code>{/if}
        </section>
      {/if}

      <section>
        <h3>Source</h3>
        <ul class="citations">
          {#each selectedNode.citations as citation}
            <li>
              <a href={`${repositoryBase}${citation.file}#L${citation.line}`} target="_blank" rel="noreferrer">
                {citation.file}:{citation.line}
              </a>
            </li>
          {/each}
        </ul>
      </section>

      <section class="path-note">
        <h3>{activePath.name}</h3>
        <p>{activePath.summary}</p>
      </section>
    </aside>
  </div>
</section>

<style>
  .atlas {
    width: min(1500px, 100%);
    margin: 0 auto;
    padding: 1rem clamp(0.75rem, 2vw, 1.75rem) 2rem;
    color: var(--paper-bone);
    font-size: 16px;
  }

  .atlas__header {
    display: flex;
    align-items: end;
    gap: 2rem;
    justify-content: space-between;
    padding: 0.65rem 0.2rem 1rem;
    border-bottom: var(--rule-hair);
  }

  .kicker,
  .stamp { color: var(--gold-candle); letter-spacing: 0.08em; }
  .kicker { margin: 0 0 0.2rem; font-size: 0.85rem; text-transform: uppercase; }
  h1,
  h2,
  h3 { font-family: var(--font-display); font-weight: 400; }
  h1 { margin: 0; font-size: 2rem; line-height: 1.05; color: var(--paper-warm); }
  .lede { max-width: 74ch; margin: 0.5rem 0 0; font-size: 1.05rem; color: color-mix(in srgb, var(--paper-bone) 80%, transparent); }
  .stamp { max-width: 24ch; margin: 0; text-align: right; font-size: 0.85rem; }

  .atlas__layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(300px, 380px);
    gap: 1rem;
    align-items: start;
    margin-top: 1rem;
  }

  .atlas__canvas { min-width: 0; border: var(--rule-hair); box-shadow: var(--shadow-deep); }

  .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    padding: 0.7rem;
    border-bottom: var(--rule-hair);
  }

  .path-tabs { display: flex; flex-wrap: wrap; gap: 0.4rem; }
  .toolbar button,
  .path-tabs button {
    padding: 0.5rem 0.85rem;
    font: 16px/1.2 ui-sans-serif, system-ui, sans-serif;
    text-transform: none;
  }
  .toolbar__spacer { flex: 1 1 1rem; }

  button.active {
    border-color: var(--gold-bright);
    color: #ffe39b;
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--gold-tarnished) 45%, transparent);
  }

  .path-summary {
    margin: 0;
    padding: 0.6rem 0.9rem;
    color: #e4d7b6;
    background: rgba(195, 154, 74, 0.08);
    border-bottom: 1px solid #2c2416;
  }

  .boundary-strip {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    border-bottom: var(--rule-hair);
    background: #0b0907;
  }
  .boundary-strip span {
    min-width: 0;
    padding: 0.55rem 0.65rem;
    border-top: 4px solid var(--boundary);
    border-right: 1px solid #2a2116;
  }
  .boundary-strip span:last-child { border-right: 0; }
  .boundary-strip strong,
  .boundary-strip small { display: block; }
  .boundary-strip strong {
    color: color-mix(in srgb, var(--boundary) 48%, #f1e8d1);
    font: 700 15px/1.2 ui-sans-serif, system-ui, sans-serif;
  }
  .boundary-strip small {
    margin-top: 0.15rem;
    color: #bfb293;
    font: 13px/1.25 ui-sans-serif, system-ui, sans-serif;
  }

  .step-rail {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    margin: 0;
    padding: 0.7rem;
    list-style: none;
    border-bottom: var(--rule-hair);
  }

  .step-rail button {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0.45rem 0.7rem;
    font: 16px/1.2 ui-sans-serif, system-ui, sans-serif;
    text-transform: none;
  }

  .step-rail button.current { background: rgba(167, 118, 34, 0.24); }
  .step-rail__number {
    display: grid;
    place-items: center;
    min-width: 1.5rem;
    height: 1.5rem;
    border-radius: 50%;
    border: 1px solid var(--gold-tarnished);
    color: var(--gold-bright);
  }
  .step-rail code { font-size: 0.95rem; color: #f0d485; }

  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem 1.1rem;
    padding: 0.7rem 0.9rem;
    color: #d8cdb2;
  }
  .legend span { display: inline-flex; align-items: center; gap: 0.45rem; }
  .legend i {
    width: 0.85rem;
    height: 0.85rem;
    background: var(--swatch, transparent);
    border: 1px solid rgba(0, 0, 0, 0.6);
  }
  .legend__route {
    width: 1.4rem !important;
    height: 0 !important;
    background: transparent !important;
    border: 0 !important;
    border-top: 3px solid #efbd4b !important;
  }

  .node-index { margin: 0; padding: 0.65rem 0.9rem 0.85rem; border-top: var(--rule-hair); }
  .node-index summary { cursor: pointer; color: #e0cfaa; font: 600 16px/1.3 ui-sans-serif, system-ui, sans-serif; }
  .node-index > div { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.65rem; }
  .node-index button {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    padding: 0.45rem 0.6rem;
    font: 600 15px/1.15 ui-sans-serif, system-ui, sans-serif;
    text-align: left;
    text-transform: none;
  }
  .node-index small { color: #baa982; font-size: 0.78rem; font-weight: 400; }

  .explainer { min-width: 0; font-size: 1.05rem; }
  .explainer__path { font-size: 0.9rem; letter-spacing: 0.08em; text-transform: uppercase; }
  .explainer__role { margin-top: -0.4rem; color: #7a5b23; font-size: 0.95rem; }
  .explainer h2 { margin-top: 0.1rem; }
  .explainer dl div { margin-bottom: 0.5rem; }
  .explainer dt { font-weight: 700; }
  .explainer dd { margin: 0; }
  .citations a {
    color: #4a3216;
    font: 700 0.95rem/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    overflow-wrap: anywhere;
  }
  .citations a:hover { color: #762d20; }
  .explainer code { font-size: 0.95rem; }

  a:focus-visible,
  button:focus-visible,
  summary:focus-visible {
    outline: 3px solid var(--gold-bright);
    outline-offset: 2px;
  }

  @media (max-width: 900px) {
    .atlas__layout { grid-template-columns: minmax(0, 1fr); }
    .atlas__header { flex-direction: column; align-items: start; gap: 0.4rem; }
    .stamp { text-align: left; }
  }

  @media (max-width: 560px) {
    .toolbar__spacer { display: none; }
    .toolbar > button { flex: 1 1 auto; }
    .step-rail { display: grid; }
    .step-rail button { width: 100%; }
    .node-index > div { display: grid; grid-template-columns: minmax(0, 1fr); }
    .boundary-strip {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .boundary-strip span:last-child { grid-column: 1 / -1; }
  }
</style>
