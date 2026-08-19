<script lang="ts">
  import ArchitectureBuilding from "./ArchitectureBuilding.svelte";
  import {
    ARCHITECTURE_NODES,
    ARCHITECTURE_PATHS,
    ROLE_META,
    nodeById,
    nodesInPainterOrder,
    type ArchitectureNode,
    type ArchitecturePath,
    type PathStep,
  } from "../../lib/dev-architecture";

  interface Segment {
    from: ArchitectureNode;
    to: ArchitectureNode;
    payload?: string;
    detail?: string;
    index: number;
  }

  const repositoryBase = "https://github.com/armantark/Dungeon-Master/blob/main/";
  const paintedNodes = nodesInPainterOrder(ARCHITECTURE_NODES);
  const defaultPath: ArchitecturePath = ARCHITECTURE_PATHS[0]!;
  const defaultNode: ArchitectureNode = ARCHITECTURE_NODES[0]!;

  let activePathId = $state<ArchitecturePath["id"]>("turn");
  let selectedNodeId = $state("foundry");
  let traceIndex = $state(-1);

  const activePath = $derived(
    ARCHITECTURE_PATHS.find((path) => path.id === activePathId) ?? defaultPath,
  );
  const selectedNode = $derived(nodeById(selectedNodeId) ?? defaultNode);
  const activeIds = $derived(new Set(activePath.steps.map((step) => step.node)));
  const selectedStep = $derived(
    activePath.steps.find((step) => step.node === selectedNodeId),
  );
  const segments = $derived.by<Segment[]>(() => {
    const result: Segment[] = [];
    for (let index = 1; index < activePath.steps.length; index += 1) {
      const previous = activePath.steps[index - 1];
      const current = activePath.steps[index];
      if (!previous || !current) continue;
      const from = nodeById(previous.node);
      const to = nodeById(current.node);
      if (!from || !to) continue;
      result.push({
        from,
        to,
        payload: current.payload,
        detail: current.detail,
        index,
      });
    }
    return result;
  });

  function choosePath(id: ArchitecturePath["id"]): void {
    activePathId = id;
    traceIndex = -1;
    selectedNodeId = ARCHITECTURE_PATHS.find((path) => path.id === id)?.steps[0]?.node ?? "foundry";
  }

  function chooseNode(id: string): void {
    selectedNodeId = id;
    const index = activePath.steps.findIndex((step) => step.node === id);
    if (index >= 0) traceIndex = index;
  }

  function chooseStep(step: PathStep, index: number): void {
    selectedNodeId = step.node;
    traceIndex = index;
  }

  function traceNext(): void {
    traceIndex = (traceIndex + 1) % activePath.steps.length;
    selectedNodeId = activePath.steps[traceIndex]?.node ?? activePath.steps[0]?.node ?? "foundry";
  }

  function resetTrace(): void {
    traceIndex = -1;
    selectedNodeId = activePath.steps[0]?.node ?? "foundry";
  }

  function stepNumber(nodeId: string): number | undefined {
    const index = activePath.steps.findIndex((step) => step.node === nodeId);
    return index >= 0 ? index + 1 : undefined;
  }

  function labelY(node: ArchitectureNode): number {
    return node.y - node.height - 7.75 * (node.width + node.depth) - 14;
  }
</script>

<section class="atlas" aria-labelledby="architecture-title">
  <header class="atlas__header">
    <div>
      <p class="kicker pixel">Dev architecture endpoint</p>
      <h1 id="architecture-title">Dungeon Master system map</h1>
      <p class="lede">
        Real control and data paths from the Svelte composer to deterministic Python,
        bounded model calls, atomic persistence, and the final replacement state.
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
        <button type="button" onclick={traceNext}>Trace next step</button>
        <button type="button" class="ghost" onclick={resetTrace}>Reset</button>
      </div>

      <div class="boundary" aria-label="Frontend to backend runtime boundary">
        <div class="boundary__side boundary__side--frontend">
          <strong>Frontend</strong>
          <span>Svelte UI · TypeScript store</span>
        </div>
        <div class="boundary__seam pixel">
          <span>POST</span>
          <span aria-hidden="true">→</span>
          <span>NDJSON</span>
        </div>
        <div class="boundary__side boundary__side--backend">
          <strong>Backend</strong>
          <span>FastAPI · Python service and rules</span>
        </div>
      </div>

      <div class="map-scroll">
        <svg viewBox="0 0 1060 620" role="img" aria-labelledby="map-title map-description">
          <title id="map-title">Isometric architecture of Dungeon Master</title>
          <desc id="map-description">
            Fifteen distinct infrastructure buildings in frontend, backend, and desktop delivery
            districts. The selected route connects them with payload-labelled arrows.
          </desc>
          <defs>
            <pattern id="iso-grid" width="62" height="31" patternUnits="userSpaceOnUse">
              <path d="M 31 0 L 62 15.5 L 31 31 L 0 15.5 Z" fill="none" stroke="#222b38" stroke-width="0.85" />
            </pattern>
            <marker id="arrow" markerWidth="8" markerHeight="8" refX="6.5" refY="3.5" orient="auto">
              <path d="M 0 0 L 7 3.5 L 0 7 Z" fill="#d3a642" />
            </marker>
          </defs>

          <path class="ground" d="M 530 10 L 1040 300 L 530 610 L 20 300 Z" />
          <path class="grid" d="M 530 10 L 1040 300 L 530 610 L 20 300 Z" />

          <g class="zones" aria-hidden="true">
            <polygon class="zone zone--frontend" points="40,235 282,112 356,160 356,425 118,438 40,356" />
            <text class="zone__name zone__name--frontend" x="64" y="218">FRONTEND</text>
            <text class="zone__sub" x="64" y="235">Svelte + TypeScript</text>

            <polygon class="zone zone--backend" points="356,72 648,8 1032,204 850,500 356,425" />
            <text class="zone__name zone__name--backend" x="468" y="48">BACKEND</text>
            <text class="zone__sub" x="468" y="65">FastAPI + Python</text>

            <polygon class="zone zone--desktop" points="118,438 356,425 850,500 710,608 345,608 185,526" />
            <text class="zone__name zone__name--desktop" x="242" y="580">DESKTOP &amp; DELIVERY</text>
            <text class="zone__sub" x="242" y="597">Tauri + sidecar + release</text>
          </g>

          <g class="routes" aria-label={`${activePath.name} data path`}>
            {#each segments as segment}
              <line
                class="route"
                class:route--traced={traceIndex >= segment.index}
                x1={segment.from.x}
                y1={segment.from.y}
                x2={segment.to.x}
                y2={segment.to.y}
                marker-end="url(#arrow)"
              />
              {#if segment.payload}
                <g class="payload" transform={`translate(${(segment.from.x + segment.to.x) / 2} ${(segment.from.y + segment.to.y) / 2 - 9})`}>
                  <rect x={-Math.max(34, segment.payload.length * 3.8)} y="-10" width={Math.max(68, segment.payload.length * 7.6)} height="20" rx="2" />
                  <text>{segment.payload}</text>
                </g>
              {/if}
            {/each}
          </g>

          <g class="buildings">
            {#each paintedNodes as node}
              <ArchitectureBuilding
                {node}
                color={ROLE_META[node.role].color}
                active={activeIds.has(node.id)}
                selected={selectedNode.id === node.id}
                step={stepNumber(node.id)}
                onselect={chooseNode}
              />
            {/each}
          </g>

          <g class="building-labels" aria-hidden="true">
            {#each ARCHITECTURE_NODES as node}
              <text
                class:label--inactive={!activeIds.has(node.id)}
                x={node.x}
                y={labelY(node)}
              >{node.name}</text>
            {/each}
          </g>
        </svg>
      </div>

      <ol class="step-rail" aria-label={`${activePath.name} path steps`}>
        {#each activePath.steps as step, index}
          {@const node = nodeById(step.node)}
          {#if node}
            <li>
              <button
                type="button"
                class:active={node.id === selectedNode.id}
                onclick={() => chooseStep(step, index)}
              >
                <span class="step-rail__number pixel">{index + 1}</span>
                <span>{node.name}</span>
                {#if step.payload}<code>{step.payload}</code>{/if}
              </button>
            </li>
          {/if}
        {/each}
      </ol>

      <div class="legend" aria-label="Architecture role legend">
        {#each Object.values(ROLE_META) as meta}
          <span><i style={`--swatch: ${meta.color}`}></i>{meta.label}</span>
        {/each}
        <span><i class="legend__route"></i>Active control/data route</span>
      </div>
    </div>

    <aside class="explainer parchment deckle" aria-live="polite">
      <p class="explainer__path pixel">{activePath.name} path · {activePath.steps.length} stops</p>
      <h2>{selectedNode.name}</h2>
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
  .kicker { margin: 0 0 0.2rem; font-size: 0.75rem; text-transform: uppercase; }
  h1,
  h2,
  h3 { font-family: var(--font-display); font-weight: 400; }
  h1 { margin: 0; font-size: 2rem; line-height: 1.05; color: var(--paper-warm); }
  .lede { max-width: 74ch; margin: 0.5rem 0 0; color: color-mix(in srgb, var(--paper-bone) 72%, transparent); }
  .stamp { max-width: 24ch; margin: 0; text-align: right; font-size: 0.7rem; }
  .atlas__layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(280px, 360px);
    gap: 1rem;
    align-items: start;
    margin-top: 1rem;
  }
  .atlas__canvas { min-width: 0; border: var(--rule-hair); box-shadow: var(--shadow-deep); }
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.45rem;
    padding: 0.7rem;
    border-bottom: var(--rule-hair);
  }
  .path-tabs { display: flex; flex-wrap: wrap; gap: 0.35rem; }
  .toolbar__spacer { flex: 1 1 1rem; }
  button.active {
    border-color: var(--gold-bright);
    color: #ffe39b;
    box-shadow: 0 0 0 1px color-mix(in srgb, var(--gold-tarnished) 45%, transparent);
  }
  .boundary {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
    gap: 0.45rem;
    align-items: stretch;
    padding: 0.55rem 0.7rem;
    background: rgba(8, 9, 12, 0.78);
    border-bottom: 1px solid #29313f;
  }
  .boundary__side {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    padding: 0.52rem 0.65rem;
    border: 1px solid;
    background: rgba(255, 255, 255, 0.025);
  }
  .boundary__side strong { font-family: var(--font-pixel); font-size: 0.78rem; font-weight: 400; }
  .boundary__side span { color: #b8bfca; font-size: 0.8rem; }
  .boundary__side--frontend { border-color: #3f8b91; }
  .boundary__side--frontend strong { color: #89d0d4; }
  .boundary__side--backend { border-color: #68788f; }
  .boundary__side--backend strong { color: #c3cede; }
  .boundary__seam {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.4rem;
    padding: 0 0.35rem;
    color: var(--gold-bright);
    font-size: 0.7rem;
  }
  .map-scroll { overflow-x: auto; background: #080b10; }
  svg { display: block; width: 100%; min-width: 820px; height: auto; }
  .ground { fill: #10151d; stroke: #303a49; stroke-width: 2; }
  .grid { fill: url(#iso-grid); opacity: 0.78; }
  .zone { stroke-width: 1.7; stroke-dasharray: 9 7; }
  .zone--frontend { fill: rgba(63, 139, 145, 0.09); stroke: #4fa5aa; }
  .zone--backend { fill: rgba(104, 120, 143, 0.09); stroke: #8291a8; }
  .zone--desktop { fill: rgba(85, 124, 94, 0.09); stroke: #70a178; }
  .zone__name,
  .zone__sub,
  .building-labels text,
  .payload text { paint-order: stroke; stroke: #080b10; stroke-linejoin: round; }
  .zone__name {
    font: 700 14px/1 var(--font-pixel);
    letter-spacing: 0.1em;
    stroke-width: 4px;
  }
  .zone__name--frontend { fill: #73c4c8; }
  .zone__name--backend { fill: #a8b5c9; }
  .zone__name--desktop { fill: #82b98b; }
  .zone__sub { fill: #929daa; font: 11px/1 var(--font-pixel); stroke-width: 3px; }
  .route { stroke: #8f6d26; stroke-width: 4; opacity: 0.62; }
  .route--traced { stroke: #efbd4b; stroke-width: 5; opacity: 1; }
  .payload rect { fill: #121720; stroke: #8b7138; stroke-width: 1; }
  .payload text {
    fill: #f0d485;
    font: 10px/1 var(--font-pixel);
    text-anchor: middle;
    dominant-baseline: middle;
    stroke-width: 3px;
  }
  .building-labels text {
    fill: #e4ded0;
    font: 12px/1 var(--font-pixel);
    text-anchor: middle;
    stroke-width: 4px;
    transition: opacity 170ms ease;
  }
  .building-labels .label--inactive { opacity: 0.38; }
  .step-rail {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    margin: 0;
    padding: 0.65rem 0.7rem;
    list-style: none;
    border-top: 1px solid #29313f;
  }
  .step-rail button {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    min-height: 2rem;
    padding: 0.35rem 0.55rem;
  }
  .step-rail__number { color: var(--gold-bright); }
  .step-rail code { color: #aab4c3; font-size: 0.68rem; }
  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.7rem 1rem;
    padding: 0.65rem 0.8rem 0.8rem;
    color: #aeb7c5;
    border-top: 1px solid #29313f;
    font: 0.68rem/1.3 var(--font-pixel);
  }
  .legend span { display: inline-flex; align-items: center; gap: 0.38rem; }
  .legend i { width: 0.75rem; height: 0.75rem; background: var(--swatch); border: 1px solid rgba(255, 255, 255, 0.24); }
  .legend__route { width: 1.5rem !important; height: 0 !important; border: 0 !important; border-top: 3px solid #efbd4b !important; }
  .explainer {
    position: sticky;
    top: 1rem;
    padding: 1.15rem 1.2rem 1.3rem;
    color: var(--ink-deep);
    box-shadow: var(--shadow-deep);
  }
  .explainer__path { margin: 0 0 0.55rem; color: #6b5528; font-size: 0.72rem; }
  .explainer h2 { margin: 0; font-size: 1.65rem; line-height: 1.05; color: var(--ink-black); }
  .explainer__summary { margin: 0.65rem 0 0.9rem; font-size: 1.03rem; line-height: 1.45; }
  .explainer dl { display: grid; gap: 0.45rem; margin: 0; }
  .explainer dl div { padding: 0.55rem 0.65rem; background: rgba(64, 45, 23, 0.075); border-left: 3px solid var(--gold-tarnished); }
  .explainer dt,
  .explainer h3 { font: 0.7rem/1.2 var(--font-pixel); letter-spacing: 0.06em; text-transform: uppercase; color: #675129; }
  .explainer dd { margin: 0.2rem 0 0; line-height: 1.35; }
  .explainer section { margin-top: 1rem; }
  .explainer h3 { margin: 0 0 0.35rem; }
  .explainer p { margin: 0; }
  .selected-edge { padding: 0.75rem; border: 1px dashed #9c7731; background: rgba(168, 133, 63, 0.08); }
  .selected-edge code { display: inline-block; margin-top: 0.45rem; color: #5b421c; }
  .citations { display: grid; gap: 0.35rem; margin: 0; padding: 0; list-style: none; }
  .citations a { color: #493a20; font: 0.7rem/1.35 var(--font-pixel); overflow-wrap: anywhere; }
  .citations a:hover { color: #7a2820; }
  .path-note { padding-top: 0.85rem; border-top: 1px solid rgba(79, 58, 27, 0.25); }
  @media (max-width: 1080px) {
    .atlas__layout { grid-template-columns: 1fr; }
    .explainer { position: static; }
  }
  @media (max-width: 680px) {
    .atlas { padding-inline: 0.55rem; }
    .atlas__header { display: block; }
    .stamp { margin-top: 0.7rem; text-align: left; }
    .boundary { grid-template-columns: 1fr; }
    .boundary__seam { justify-content: flex-start; padding: 0.25rem 0.65rem; }
    .boundary__side { flex-wrap: wrap; }
    .toolbar__spacer { display: none; }
    .toolbar { align-items: stretch; }
    .path-tabs { width: 100%; }
    .path-tabs button { flex: 1 1 auto; }
  }
  @media (prefers-reduced-motion: reduce) {
    .building-labels text { transition: none; }
  }
</style>
