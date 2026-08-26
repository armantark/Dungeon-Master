<script lang="ts">
  import { onMount } from "svelte";
  import { SvelteSet } from "svelte/reactivity";

  import { ROLE_META, type ArchitecturePath } from "../../lib/dev-architecture";
  import { PLACEMENTS, ZONES } from "../../lib/architecture-layout";
  import { placeLabels, type LabelCandidate } from "../../lib/architecture-labels";
  import {
    createArchitectureScene,
    type ArchitectureSceneApi,
    type SceneAnchors,
  } from "./scene/architecture-scene";

  let {
    activePath,
    selectedNodeId,
    traceIndex,
    onSelect,
  }: {
    activePath: ArchitecturePath;
    selectedNodeId: string;
    traceIndex: number;
    onSelect: (id: string) => void;
  } = $props();

  let frameEl: HTMLDivElement;
  let canvasEl: HTMLCanvasElement;

  const codeEls = new Map<string, HTMLElement>();
  const sectionEls = new Map<string, HTMLElement>();

  let scene: ArchitectureSceneApi | null = null;
  let hoveredNodeId = $state<string | null>(null);
  let focusedNodeId = $state<string | null>(null);
  let compact = $state(false);

  const stepIndex = $derived(new Map(activePath.steps.map((step, index) => [step.node, index])));
  const currentStep = $derived(traceIndex >= 0 ? activePath.steps[traceIndex] : undefined);
  const previousNodeId = $derived(
    traceIndex >= 1 ? activePath.steps[traceIndex - 1]?.node : undefined,
  );

  function collect(element: HTMLElement, args: [Map<string, HTMLElement>, string]) {
    const [store, id] = args;
    store.set(id, element);
    return {
      destroy() {
        store.delete(id);
      },
    };
  }

  function isEmphasised(id: string): boolean {
    return (
      id === selectedNodeId ||
      id === hoveredNodeId ||
      id === focusedNodeId ||
      id === currentStep?.node ||
      id === previousNodeId
    );
  }

  /**
   * Declutter priority. Section labels are the map's legend and never move for
   * a code; after them, whatever the reader is actually looking at claims its
   * spot and the rest step aside.
   */
  function codeOrder(): string[] {
    const order: string[] = [];
    const seen = new SvelteSet<string>();
    const push = (id: string | null | undefined) => {
      if (!id || seen.has(id)) return;
      seen.add(id);
      order.push(id);
    };

    push(currentStep?.node);
    push(previousNodeId);
    push(selectedNodeId);
    push(hoveredNodeId);
    push(focusedNodeId);
    for (const step of activePath.steps) push(step.node);
    for (const placement of PLACEMENTS) push(placement.id);
    return order;
  }

  function layoutOverlays(anchors: SceneAnchors): void {
    const candidates: LabelCandidate[] = [];
    const show = (element: HTMLElement, visible: boolean) => {
      element.style.opacity = visible ? "1" : "0";
      element.style.pointerEvents = visible ? "auto" : "none";
    };
    const add = (
      id: string,
      element: HTMLElement | undefined,
      point?: { x: number; y: number },
    ) => {
      if (!element || !point || element.offsetWidth === 0) return;
      candidates.push({
        id,
        anchorX: point.x,
        anchorY: point.y,
        width: element.offsetWidth,
        height: element.offsetHeight,
      });
    };

    for (const zone of ZONES) {
      add(`zone:${zone.id}`, sectionEls.get(zone.id), anchors.zones.get(zone.id));
    }

    for (const id of codeOrder()) {
      const element = codeEls.get(id);
      const point = anchors.nodes.get(id);
      if (!element) continue;
      // A code whose building has been panned or zoomed out of frame would
      // otherwise be clamped to the canvas edge and pile up there.
      const framed =
        point !== undefined &&
        point.x > -40 &&
        point.x < anchors.width + 40 &&
        point.y > -40 &&
        point.y < anchors.height + 40;
      if (!framed && !isEmphasised(id)) {
        show(element, false);
        continue;
      }
      add(id, element, point);
    }

    for (const placed of placeLabels(candidates, anchors, { anchorGap: 6, gap: 4 })) {
      const element = placed.id.startsWith("zone:")
        ? sectionEls.get(placed.id.slice(5))
        : codeEls.get(placed.id);
      if (!element) continue;
      element.style.transform = `translate3d(${Math.round(placed.x)}px, ${Math.round(placed.y)}px, 0)`;
      show(element, true);
    }
  }

  onMount(() => {
    const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
    scene = createArchitectureScene({
      canvas: canvasEl,
      reducedMotion: motionQuery.matches,
      onHover: (id) => {
        hoveredNodeId = id;
      },
      onPick: onSelect,
      onAnchors: layoutOverlays,
    });
    scene.setState({
      path: activePath,
      traceIndex,
      selectedNodeId,
      hoveredNodeId: null,
      compact,
    });

    const observer = new ResizeObserver(([entry]) => {
      const box = entry?.contentRect;
      if (!box || box.width < 2 || box.height < 2) return;
      compact = box.width < 620;
      scene?.setViewport(box.width, box.height);
    });
    observer.observe(frameEl);

    return () => {
      observer.disconnect();
      scene?.dispose();
      scene = null;
    };
  });

  $effect(() => {
    scene?.setState({
      path: activePath,
      traceIndex,
      selectedNodeId,
      // Keyboard focus lights a building the same way a hover does, so tabbing
      // the drawing is not a second-class way to read it.
      hoveredNodeId: hoveredNodeId ?? focusedNodeId,
      compact,
    });
  });
</script>

<div class="sheet" bind:this={frameEl}>
  <canvas bind:this={canvasEl} aria-hidden="true"></canvas>

  <div class="marks">
    {#each ZONES as zone (zone.id)}
      <span class="section" aria-hidden="true" use:collect={[sectionEls, zone.id]}>
        <b>{String(zone.index).padStart(2, "0")}</b>{zone.label}
      </span>
    {/each}

    {#each PLACEMENTS as placement (placement.id)}
      {@const step = stepIndex.get(placement.id)}
      <button
        type="button"
        class="code"
        class:code--path={step !== undefined}
        class:code--open={isEmphasised(placement.id)}
        class:code--selected={placement.id === selectedNodeId}
        aria-pressed={placement.id === selectedNodeId}
        aria-label={`${placement.code}. ${placement.node.name}. ${
          ROLE_META[placement.node.role].label
        }.${
          step === undefined ? "" : ` Stop ${step + 1} of the ${activePath.name} path.`
        } ${placement.node.responsibility}`}
        onclick={() => onSelect(placement.id)}
        onfocus={() => (focusedNodeId = placement.id)}
        onblur={() => (focusedNodeId = null)}
        onpointerenter={() => (hoveredNodeId = placement.id)}
        onpointerleave={() => (hoveredNodeId = null)}
        use:collect={[codeEls, placement.id]}
      >
        {placement.code}{#if step !== undefined}<sup>{step + 1}</sup>{/if}
      </button>
    {/each}
  </div>

  <div class="tools">
    <button type="button" aria-label="Zoom in" onclick={() => scene?.zoomBy(1.3)}>+</button>
    <button type="button" aria-label="Zoom out" onclick={() => scene?.zoomBy(1 / 1.3)}>−</button>
    <button type="button" onclick={() => scene?.fit()}>Fit</button>
  </div>
</div>

<style>
  .sheet {
    position: relative;
    min-height: 0;
    height: 100%;
    overflow: hidden;
    background: var(--atlas-paper);
    isolation: isolate;
  }

  canvas {
    display: block;
    width: 100%;
    height: 100%;
    cursor: grab;
    touch-action: manipulation;
  }

  .marks {
    position: absolute;
    inset: 0;
    pointer-events: none;
  }

  /* --- section labels --------------------------------------------------- */

  .section {
    position: absolute;
    top: 0;
    left: 0;
    display: inline-flex;
    align-items: baseline;
    gap: 0.3rem;
    padding: 0.05rem 0.2rem;
    color: var(--atlas-ink);
    font:
      600 10.5px/1.4 ui-sans-serif,
      system-ui,
      sans-serif;
    letter-spacing: 0.11em;
    text-transform: uppercase;
    white-space: nowrap;
    opacity: 0;
  }
  .section b {
    padding: 0 0.22rem;
    color: var(--atlas-paper);
    background: var(--atlas-ink);
    font-weight: 700;
    letter-spacing: 0.06em;
  }

  /* --- drawing codes ---------------------------------------------------- */

  .code {
    position: absolute;
    top: 0;
    left: 0;
    padding: 0.05rem 0.24rem;
    color: var(--atlas-ink);
    background: color-mix(in srgb, var(--atlas-paper) 82%, #ffffff);
    border: 1px solid var(--atlas-rule);
    border-radius: 0;
    box-shadow: none;
    text-shadow: none;
    font:
      600 11px/1.35 ui-monospace,
      SFMono-Regular,
      Menlo,
      Consolas,
      monospace;
    letter-spacing: 0.06em;
    text-transform: none;
    white-space: nowrap;
    pointer-events: auto;
    cursor: pointer;
    opacity: 0;
    transition:
      color 110ms ease,
      background 110ms ease,
      border-color 110ms ease;
  }
  .code::before {
    display: none;
  }
  .code sup {
    margin-left: 0.15rem;
    font-size: 8.5px;
    vertical-align: super;
  }

  .code--path {
    border-color: color-mix(in srgb, var(--atlas-ink) 55%, transparent);
  }

  .code--open,
  .code:hover,
  .code:focus-visible {
    z-index: 3;
    color: var(--atlas-paper);
    background: var(--atlas-ink);
    border-color: var(--atlas-ink);
  }

  .code--selected {
    z-index: 4;
    outline: 1px solid var(--atlas-ink);
    outline-offset: 2px;
  }

  /* --- viewport tools --------------------------------------------------- */

  .tools {
    position: absolute;
    top: 0.5rem;
    right: 0.5rem;
    z-index: 6;
    display: flex;
    gap: 1px;
    background: var(--atlas-rule);
    border: 1px solid var(--atlas-rule);
  }
  .tools button {
    min-width: 1.8rem;
    padding: 0.2rem 0.4rem;
    color: var(--atlas-ink);
    background: var(--atlas-panel);
    border: 0;
    border-radius: 0;
    box-shadow: none;
    text-shadow: none;
    font:
      600 12px/1.5 ui-sans-serif,
      system-ui,
      sans-serif;
    letter-spacing: 0;
    text-transform: none;
    cursor: pointer;
  }
  .tools button::before {
    display: none;
  }
  .tools button:hover {
    color: var(--atlas-paper);
    background: var(--atlas-ink);
    filter: none;
  }
  .code:focus-visible,
  .tools button:focus-visible {
    outline: 2px solid var(--atlas-ink);
    outline-offset: 2px;
  }

  /*
   * Codes for buildings outside the current view are hidden with an inline
   * opacity; a keyboard user must still see the one they land on.
   */
  .code:focus-visible {
    opacity: 1 !important;
    pointer-events: auto !important;
  }

  @media (prefers-reduced-motion: reduce) {
    .code {
      transition: none;
    }
  }
</style>
