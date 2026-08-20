<script lang="ts">
  import "@xyflow/svelte/dist/style.css";
  import { SvelteFlow, Background, MarkerType } from "@xyflow/svelte";
  import type { Node, Edge } from "@xyflow/svelte";
  import ArchitectureNode from "./ArchitectureNode.svelte";
  import ArchitectureRegion from "./ArchitectureRegion.svelte";
  import {
    ARCHITECTURE_NODES,
    ARCHITECTURE_PATHS,
    ROLE_META,
    nodeById,
    type ArchitectureNode as ArchNode,
    type ArchitecturePath,
    type PathStep,
  } from "../../lib/dev-architecture";

  const repositoryBase = "https://github.com/armantark/Dungeon-Master/blob/main/";

  interface Region {
    id: string;
    label: string;
    sub: string;
    tint: string;
    x: number;
    y: number;
    width: number;
    height: number;
  }

  const REGIONS: Region[] = [
    {
      id: "region-frontend",
      label: "Frontend",
      sub: "Svelte UI · TypeScript store",
      tint: "#4fa5aa",
      x: 20, y: 20, width: 240, height: 540,
    },
    {
      id: "region-transport",
      label: "Transport",
      sub: "HTTP · NDJSON stream boundary",
      tint: "#c9a24e",
      x: 280, y: 20, width: 230, height: 230,
    },
    {
      id: "region-backend",
      label: "Backend",
      sub: "FastAPI · deterministic Python · bounded model calls",
      tint: "#8291a8",
      x: 530, y: 20, width: 540, height: 540,
    },
    {
      id: "region-persistence",
      label: "Persistence",
      sub: "Atomic writes · canonical saves",
      tint: "#c0a04f",
      x: 20, y: 580, width: 470, height: 210,
    },
    {
      id: "region-desktop",
      label: "Desktop & Delivery",
      sub: "Tauri shell · sidecar · release",
      tint: "#70a178",
      x: 510, y: 580, width: 560, height: 210,
    },
  ];

  // Positions are relative to each parent region. Svelte Flow owns viewport,
  // edge routing, zoom, and pan while the regions keep trust boundaries stable.
  const POSITIONS: Record<string, { x: number; y: number }> = {
    composer: { x: 20, y: 95 },
    relay: { x: 20, y: 270 },
    homes: { x: 20, y: 430 },
    depot: { x: 15, y: 100 },
    foundry: { x: 35, y: 95 },
    router: { x: 305, y: 95 },
    memory: { x: 35, y: 260 },
    oracle: { x: 305, y: 260 },
    narrative: { x: 35, y: 420 },
    loom: { x: 305, y: 420 },
    vault: { x: 20, y: 80 },
    library: { x: 250, y: 80 },
    shell: { x: 10, y: 80 },
    sidecar: { x: 180, y: 80 },
    crane: { x: 350, y: 80 },
  };

  const NODE_REGIONS: Record<string, string> = {
    composer: "region-frontend",
    relay: "region-frontend",
    homes: "region-frontend",
    depot: "region-transport",
    foundry: "region-backend",
    memory: "region-backend",
    router: "region-backend",
    oracle: "region-backend",
    narrative: "region-backend",
    loom: "region-backend",
    vault: "region-persistence",
    library: "region-persistence",
    shell: "region-desktop",
    sidecar: "region-desktop",
    crane: "region-desktop",
  };

  const NODE_WIDTH = 200;
  const NODE_HEIGHT = 90;

  const nodeTypes = { arch: ArchitectureNode, region: ArchitectureRegion } as never;

  const defaultPath: ArchitecturePath = ARCHITECTURE_PATHS[0]!;
  const defaultNode: ArchNode = ARCHITECTURE_NODES[0]!;

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

  function stepNumber(nodeId: string): number | undefined {
    const index = activePath.steps.findIndex((step) => step.node === nodeId);
    return index >= 0 ? index + 1 : undefined;
  }

  const flowNodes = $derived.by<Node[]>(() => {
    const regions: Node[] = REGIONS.map((region) => ({
      id: region.id,
      type: "region",
      position: { x: region.x, y: region.y },
      data: { label: region.label, sub: region.sub, tint: region.tint },
      width: region.width,
      height: region.height,
      draggable: false,
      selectable: false,
      connectable: false,
      focusable: false,
      zIndex: -10,
    }));
    const nodes: Node[] = ARCHITECTURE_NODES.map((node) => {
      const regionId = NODE_REGIONS[node.id];
      const position = POSITIONS[node.id] ?? { x: 0, y: 0 };
      return {
        id: node.id,
        type: "arch",
        position,
        data: {
          name: node.name,
          roleLabel: ROLE_META[node.role].label,
          color: ROLE_META[node.role].color,
          active: activeIds.has(node.id),
          selected: selectedNode.id === node.id,
          step: stepNumber(node.id),
          id: node.id,
          onSelect: chooseNode,
        },
        width: NODE_WIDTH,
        height: NODE_HEIGHT,
        draggable: false,
        connectable: false,
        focusable: false,
        ...(regionId ? { parentId: regionId } : {}),
      };
    });
    return [...regions, ...nodes];
  });

  const flowEdges = $derived.by<Edge[]>(() => {
    const edges: Edge[] = [];
    for (let index = 1; index < activePath.steps.length; index += 1) {
      const previous = activePath.steps[index - 1];
      const current = activePath.steps[index];
      if (!previous || !current) continue;
      const traced = traceIndex < 0 || traceIndex >= index;
      edges.push({
        id: `${activePath.id}-${index}-${previous.node}-${current.node}`,
        source: previous.node,
        target: current.node,
        type: "smoothstep",
        label: traceIndex === index ? current.payload : undefined,
        animated: false,
        zIndex: 5,
        class: traced ? "arch-edge arch-edge--traced" : "arch-edge",
        labelStyle: "color:#f0d485;font-size:16px;font-family:var(--font-pixel);background:#1a150d;border:1px solid #8b7138;padding:5px 8px;border-radius:2px",
        markerEnd: { type: MarkerType.ArrowClosed, color: traced ? "#efbd4b" : "#9a7a30" },
      });
    }
    return edges;
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

      <p class="path-summary">{activePath.summary}</p>

      <div class="flow-frame">
        <SvelteFlow
          nodes={flowNodes}
          edges={flowEdges}
          {nodeTypes}
          fitView
          minZoom={0.2}
          maxZoom={1.6}
          nodesDraggable={false}
          nodesConnectable={false}
          nodesFocusable={false}
          elementsSelectable={false}
          zoomOnScroll={true}
          panOnDrag={true}
          proOptions={{ hideAttribution: true }}
          colorMode="dark"
        >
          <Background gap={28} size={1} bgColor="#0d0b08" patternColor="#241d14" />
        </SvelteFlow>
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
    font-size: 16px;
    padding: 0.5rem 0.85rem;
    font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
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
    font-size: 1rem;
    color: #e4d7b6;
    background: rgba(195, 154, 74, 0.08);
    border-bottom: 1px solid #2c2416;
  }

  .flow-frame {
    height: 660px;
    background: #0d0b08;
    border-bottom: var(--rule-hair);
  }

  /* Svelte Flow chrome: readable, high-contrast, brass-framed. */
  .flow-frame :global(.svelte-flow) {
    font-size: 16px;
  }
  .flow-frame :global(.svelte-flow__edge-path) {
    stroke: #9a7a30;
    stroke-width: 3;
  }
  .flow-frame :global(.arch-edge--traced .svelte-flow__edge-path) {
    stroke: #efbd4b;
    stroke-width: 4;
  }
  .flow-frame :global(.svelte-flow__edge-textbg) {
    fill: #1a150d;
  }
  .flow-frame :global(.svelte-flow__handle) {
    opacity: 0;
    pointer-events: none;
  }
  .flow-frame :global(.svelte-flow__node-arch:focus-visible),
  .flow-frame :global(.svelte-flow__node:focus-visible) {
    outline: 3px solid var(--gold-bright);
    outline-offset: 3px;
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
    font-size: 16px;
    padding: 0.45rem 0.7rem;
    font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    text-transform: none;
  }
  .step-rail__number {
    display: grid;
    place-items: center;
    min-width: 1.5rem;
    height: 1.5rem;
    border-radius: 50%;
    border: 1px solid var(--gold-tarnished);
    color: var(--gold-bright);
    font-size: 16px;
  }
  .step-rail code {
    font-size: 0.95rem;
    color: #f0d485;
  }

  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem 1.1rem;
    padding: 0.7rem 0.9rem;
    font-size: 16px;
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
    background: transparent !important;
    border-top: 3px solid #efbd4b !important;
    border-left: none;
    border-right: none;
    border-bottom: none;
    height: 0 !important;
    width: 1.4rem !important;
  }

  .explainer {
    min-width: 0;
    font-size: 1.05rem;
  }
  .explainer__path { font-size: 0.9rem; letter-spacing: 0.08em; text-transform: uppercase; }
  .explainer__role { font-size: 0.95rem; color: #7a5b23; margin-top: -0.4rem; }
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
  button:focus-visible {
    outline: 3px solid var(--gold-bright);
    outline-offset: 2px;
  }

  @media (max-width: 900px) {
    .atlas__layout {
      grid-template-columns: minmax(0, 1fr);
    }
    .flow-frame { height: 460px; }
    .atlas__header { flex-direction: column; align-items: start; gap: 0.4rem; }
    .stamp { text-align: left; }
  }

  @media (prefers-reduced-motion: reduce) {
    .flow-frame :global(.svelte-flow__edge-path) {
      transition: none !important;
    }
  }
</style>
