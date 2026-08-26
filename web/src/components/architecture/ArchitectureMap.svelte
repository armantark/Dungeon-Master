<script lang="ts">
  import { onMount } from "svelte";

  import ArchitectureScene from "./ArchitectureScene.svelte";
  import ArchitectureExplainer from "./ArchitectureExplainer.svelte";
  import {
    ARCHITECTURE_NODES,
    ARCHITECTURE_PATHS,
    nodeById,
    type ArchitectureNode,
    type ArchitecturePath,
  } from "../../lib/dev-architecture";
  import { PLACEMENTS, ZONES, membersOf } from "../../lib/architecture-layout";

  const defaultPath: ArchitecturePath = ARCHITECTURE_PATHS[0]!;
  const defaultNode: ArchitectureNode = ARCHITECTURE_NODES[0]!;

  const roleCount = (...roles: ArchitectureNode["role"][]) =>
    ARCHITECTURE_NODES.filter((node) => roles.includes(node.role)).length;

  /** Every figure is counted from the same data the drawing is built from. */
  const TELEMETRY = [
    { label: "Components", value: ARCHITECTURE_NODES.length },
    { label: "Paths", value: ARCHITECTURE_PATHS.length },
    { label: "Boundaries", value: ZONES.length },
    { label: "Deterministic", value: roleCount("python") },
    { label: "Model calls", value: roleCount("structured", "prose") },
    { label: "Canonical stores", value: roleCount("persist") },
  ] as const;

  let activePathId = $state<ArchitecturePath["id"]>(defaultPath.id);
  let selectedNodeId = $state(defaultPath.steps[0]?.node ?? defaultNode.id);
  let traceIndex = $state(-1);
  let narrow = $state(false);

  const activePath = $derived(
    ARCHITECTURE_PATHS.find((path) => path.id === activePathId) ?? defaultPath,
  );
  const selectedNode = $derived(nodeById(selectedNodeId) ?? defaultNode);
  const stepIndex = $derived(new Map(activePath.steps.map((step, index) => [step.node, index])));
  const selectedStepIndex = $derived(stepIndex.get(selectedNodeId) ?? -1);
  const selectedStep = $derived(
    selectedStepIndex >= 0 ? activePath.steps[selectedStepIndex] : undefined,
  );
  const atEnd = $derived(traceIndex >= activePath.steps.length - 1);
  const currentStep = $derived(traceIndex >= 0 ? activePath.steps[traceIndex] : undefined);
  const currentNode = $derived(currentStep ? nodeById(currentStep.node) : undefined);
  const announcement = $derived(
    traceIndex < 0
      ? `${activePath.name} path ready. ${activePath.steps.length} stops.`
      : `Stop ${traceIndex + 1} of ${activePath.steps.length}. ${currentNode?.name ?? ""}. ${
          currentStep?.payload ?? ""
        }`,
  );

  function choosePath(id: ArchitecturePath["id"]): void {
    const path = ARCHITECTURE_PATHS.find((candidate) => candidate.id === id) ?? defaultPath;
    activePathId = path.id;
    traceIndex = -1;
    selectedNodeId = path.steps[0]?.node ?? defaultNode.id;
  }

  function goToStep(index: number): void {
    const clamped = Math.max(-1, Math.min(index, activePath.steps.length - 1));
    traceIndex = clamped;
    selectedNodeId =
      activePath.steps[Math.max(0, clamped)]?.node ?? activePath.steps[0]?.node ?? defaultNode.id;
  }

  onMount(() => {
    const query = window.matchMedia("(max-width: 860px)");
    const sync = () => (narrow = query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  });
</script>

<section class="atlas" aria-labelledby="architecture-title">
  <header class="telemetry">
    <h1 id="architecture-title">
      Dungeon Master <span>system plan</span>
    </h1>
    <dl class="telemetry__figures">
      {#each TELEMETRY as figure (figure.label)}
        <div>
          <dt>{figure.label}</dt>
          <dd>{figure.value}</dd>
        </div>
      {/each}
    </dl>
    <div class="telemetry__paths" role="group" aria-label="Choose a path to trace">
      {#each ARCHITECTURE_PATHS as path (path.id)}
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
  </header>

  <div class="atlas__body">
    <div class="rail">
      <div class="trace" role="group" aria-label="Step through the path">
        <p class="trace__where">
          {#if traceIndex < 0}
            {activePath.name} · overview
          {:else}
            {activePath.name} · stop {traceIndex + 1} of {activePath.steps.length}
          {/if}
        </p>
        <div class="trace__buttons">
          <button
            type="button"
            disabled={traceIndex < 0}
            aria-label="Previous stop"
            onclick={() => goToStep(traceIndex - 1)}>◀</button
          >
          <button
            type="button"
            class="trace__next"
            onclick={() => goToStep(atEnd ? 0 : traceIndex + 1)}
          >
            {atEnd ? "Restart" : traceIndex < 0 ? "Trace" : "Next"}
          </button>
          <button
            type="button"
            disabled={traceIndex < 0}
            aria-label="Back to overview"
            onclick={() => goToStep(-1)}>Reset</button
          >
        </div>
      </div>

      <details class="index" open={!narrow}>
        <summary>Index · {PLACEMENTS.length} components</summary>

        <div class="index__scroll">
          {#each ZONES as zone (zone.id)}
            <section class="group">
              <h2>
                <b>{String(zone.index).padStart(2, "0")}</b>
                {zone.label}
                <em>{zone.detail}</em>
              </h2>
              {#each membersOf(zone.id) as placement (placement.id)}
                {@const stop = stepIndex.get(placement.id)}
                <button
                  type="button"
                  class="row"
                  class:active={selectedNodeId === placement.id}
                  class:row--current={traceIndex >= 0 && traceIndex === stop}
                  aria-pressed={selectedNodeId === placement.id}
                  onclick={() => (selectedNodeId = placement.id)}
                >
                  <span class="row__code">{placement.code}</span>
                  <span class="row__name">{placement.node.name}</span>
                  {#if stop !== undefined}<span class="row__stop">{stop + 1}</span>{/if}
                </button>
              {/each}
            </section>
          {/each}
        </div>
      </details>
    </div>

    <div class="plan">
      <ArchitectureScene
        {activePath}
        {selectedNodeId}
        {traceIndex}
        onSelect={(id: string) => {
          selectedNodeId = id;
        }}
      />

      {#if traceIndex >= 1 && currentStep}
        <p class="hop">
          <span class="hop__count">{traceIndex + 1}/{activePath.steps.length}</span>
          {currentNode?.name}
          {#if currentStep.payload}<code>{currentStep.payload}</code>{/if}
        </p>
      {:else}
        <p class="hop hop__summary">{activePath.summary}</p>
      {/if}

      <p class="hints">
        Drag to pan · Scroll or ± to zoom · Hover or tab a code to light its building · Click to
        read it · Trace walks one hop at a time
      </p>
    </div>

    <details class="reader-wrap" open={!narrow}>
      <summary>Reading panel · {selectedNode.name}</summary>
      <ArchitectureExplainer
        node={selectedNode}
        path={activePath}
        step={selectedStep}
        stepNumber={selectedStepIndex >= 0 ? selectedStepIndex + 1 : undefined}
        isCurrentStep={selectedStepIndex >= 0 && selectedStepIndex === traceIndex}
      />
    </details>
  </div>

  <p class="sr-only" aria-live="polite">{announcement}</p>
</section>

<style>
  .atlas {
    /* One desaturated paper field; ink is the only other pigment. */
    --atlas-paper: #c7c4ab;
    --atlas-panel: #d0cdb5;
    --atlas-ink: #16170f;
    --atlas-ink-body: #2c2e23;
    --atlas-ink-soft: #4e5142;
    --atlas-rule: #9a9880;
    --atlas-highlight: #bcbf96;

    display: grid;
    grid-template-rows: auto minmax(0, 1fr);
    height: 100dvh;
    color: var(--atlas-ink-body);
    background: var(--atlas-paper);
    font-family: ui-sans-serif, system-ui, sans-serif;
  }

  /* --- telemetry strip --------------------------------------------------- */

  .telemetry {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 1.1rem;
    padding: 0.35rem 0.75rem;
    background: var(--atlas-panel);
    border-bottom: 1px solid var(--atlas-rule);
  }

  h1 {
    margin: 0;
    color: var(--atlas-ink);
    font:
      600 12px/1.5 ui-sans-serif,
      system-ui,
      sans-serif;
    letter-spacing: 0.13em;
    text-transform: uppercase;
  }
  h1 span {
    color: var(--atlas-ink-soft);
    font-weight: 400;
  }

  .telemetry__figures {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem 1rem;
    margin: 0;
  }
  .telemetry__figures div {
    display: flex;
    align-items: baseline;
    gap: 0.3rem;
  }
  .telemetry__figures dt {
    color: var(--atlas-ink-soft);
    font:
      10.5px/1.5 ui-sans-serif,
      system-ui,
      sans-serif;
    letter-spacing: 0.09em;
    text-transform: uppercase;
  }
  .telemetry__figures dd {
    margin: 0;
    color: var(--atlas-ink);
    font:
      600 12px/1.4 ui-monospace,
      SFMono-Regular,
      Menlo,
      Consolas,
      monospace;
  }

  .telemetry__paths {
    display: flex;
    flex-wrap: wrap;
    gap: 1px;
    margin-left: auto;
    background: var(--atlas-rule);
    border: 1px solid var(--atlas-rule);
  }

  /* --- three column body ------------------------------------------------- */

  .atlas__body {
    display: grid;
    grid-template-columns: 232px minmax(0, 1fr) 324px;
    min-height: 0;
  }

  /*
   * The trace controls sit above the index rather than inside it, so they stay
   * reachable when the index collapses to a summary on a narrow screen.
   */
  .rail {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr);
    min-height: 0;
    background: var(--atlas-panel);
    border-right: 1px solid var(--atlas-rule);
  }

  /* The summary is hidden on desktop, so the index is a single filling row. */
  .index {
    display: grid;
    grid-template-rows: minmax(0, 1fr);
    min-height: 0;
  }
  .index__scroll {
    min-height: 0;
    padding-bottom: 1.2rem;
    overflow-y: auto;
  }

  .trace {
    padding: 0.5rem 0.55rem;
    background: var(--atlas-panel);
    border-bottom: 1px solid var(--atlas-rule);
  }
  .trace__where {
    margin: 0 0 0.35rem;
    color: var(--atlas-ink);
    font:
      600 10.5px/1.5 ui-sans-serif,
      system-ui,
      sans-serif;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .trace__buttons {
    display: flex;
    gap: 1px;
    background: var(--atlas-rule);
    border: 1px solid var(--atlas-rule);
  }
  .trace__next {
    flex: 1 1 auto;
  }

  .group {
    padding-top: 0.55rem;
  }
  .group h2 {
    display: flex;
    align-items: baseline;
    gap: 0.35rem;
    margin: 0 0 0.25rem;
    padding: 0 0.55rem 0.2rem;
    border-bottom: 1px solid var(--atlas-rule);
    color: var(--atlas-ink);
    font:
      600 10.5px/1.5 ui-sans-serif,
      system-ui,
      sans-serif;
    letter-spacing: 0.09em;
    text-transform: uppercase;
  }
  .group h2 b {
    padding: 0 0.2rem;
    color: var(--atlas-panel);
    background: var(--atlas-ink);
  }
  .group h2 em {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    color: var(--atlas-ink-soft);
    font-style: normal;
    font-weight: 400;
    font-size: 9.5px;
    letter-spacing: 0.04em;
    text-align: right;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .row {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    width: 100%;
    padding: 0.28rem 0.55rem;
    color: var(--atlas-ink-body);
    background: transparent;
    border: 0;
    border-radius: 0;
    box-shadow: none;
    text-shadow: none;
    font:
      12.5px/1.4 ui-sans-serif,
      system-ui,
      sans-serif;
    letter-spacing: 0;
    text-align: left;
    text-transform: none;
    cursor: pointer;
  }
  /* The app's cast-iron button skin has no place on a paper sheet. */
  .row::before {
    display: none;
  }
  .row:hover {
    color: var(--atlas-ink);
    background: color-mix(in srgb, var(--atlas-ink) 8%, transparent);
    filter: none;
  }
  .row__code {
    flex: 0 0 auto;
    min-width: 1.55rem;
    padding: 0 0.2rem;
    border: 1px solid var(--atlas-rule);
    font:
      600 10.5px/1.5 ui-monospace,
      SFMono-Regular,
      Menlo,
      Consolas,
      monospace;
    letter-spacing: 0.05em;
    text-align: center;
  }
  .row__name {
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .row__stop {
    flex: 0 0 auto;
    min-width: 1.1rem;
    color: var(--atlas-ink-soft);
    font:
      600 10px/1.5 ui-monospace,
      SFMono-Regular,
      Menlo,
      Consolas,
      monospace;
    text-align: right;
  }
  .row.active {
    color: var(--atlas-panel);
    background: var(--atlas-ink);
  }
  .row.active .row__code {
    border-color: var(--atlas-panel);
  }
  .row.active .row__stop {
    color: var(--atlas-panel);
  }
  .row--current .row__stop {
    color: var(--atlas-ink);
    background: var(--atlas-highlight);
  }

  /* --- plan column ------------------------------------------------------- */

  .plan {
    display: grid;
    grid-template-rows: minmax(0, 1fr) auto auto;
    min-width: 0;
    min-height: 0;
  }

  .hop {
    display: flex;
    align-items: baseline;
    gap: 0.45rem;
    margin: 0;
    padding: 0.35rem 0.7rem;
    background: var(--atlas-panel);
    border-top: 1px solid var(--atlas-rule);
    color: var(--atlas-ink);
    font:
      600 12px/1.5 ui-sans-serif,
      system-ui,
      sans-serif;
  }
  .hop code {
    min-width: 0;
    padding: 0 0.2rem;
    background: var(--atlas-highlight);
    font:
      11.5px/1.5 ui-monospace,
      SFMono-Regular,
      Menlo,
      Consolas,
      monospace;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .hop__count {
    padding: 0 0.22rem;
    color: var(--atlas-panel);
    background: var(--atlas-ink);
    font:
      600 10.5px/1.6 ui-monospace,
      SFMono-Regular,
      Menlo,
      Consolas,
      monospace;
  }
  .hop__summary {
    color: var(--atlas-ink-body);
    font-weight: 400;
  }

  .hints {
    margin: 0;
    padding: 0.3rem 0.7rem;
    background: var(--atlas-panel);
    border-top: 1px solid var(--atlas-rule);
    color: var(--atlas-ink-soft);
    font:
      10.5px/1.5 ui-sans-serif,
      system-ui,
      sans-serif;
    letter-spacing: 0.05em;
  }

  /* --- reading panel wrapper --------------------------------------------- */

  .reader-wrap {
    display: grid;
    grid-template-rows: minmax(0, 1fr);
    min-width: 0;
    min-height: 0;
  }

  /* --- controls ---------------------------------------------------------- */

  .telemetry__paths button,
  .trace__buttons button {
    padding: 0.3rem 0.55rem;
    color: var(--atlas-ink);
    background: var(--atlas-panel);
    border: 0;
    border-radius: 0;
    box-shadow: none;
    text-shadow: none;
    font:
      600 11.5px/1.5 ui-sans-serif,
      system-ui,
      sans-serif;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    cursor: pointer;
  }
  .telemetry__paths button::before,
  .trace__buttons button::before {
    display: none;
  }
  .telemetry__paths button:hover:not(:disabled),
  .trace__buttons button:hover:not(:disabled) {
    color: var(--atlas-paper);
    background: var(--atlas-ink);
    filter: none;
  }
  .telemetry__paths button:disabled,
  .trace__buttons button:disabled {
    color: var(--atlas-ink-soft);
    opacity: 0.5;
    cursor: not-allowed;
  }
  .telemetry__paths button.active {
    color: var(--atlas-paper);
    background: var(--atlas-ink);
  }

  button:focus-visible,
  summary:focus-visible {
    outline: 2px solid var(--atlas-ink);
    outline-offset: -2px;
  }

  summary {
    display: none;
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }

  @media (max-width: 1180px) {
    .atlas__body {
      grid-template-columns: 204px minmax(0, 1fr) 290px;
    }
  }

  /*
   * Below 860px the three columns stack. The plan keeps a usable share of the
   * screen and the two rails become collapsible regions, so the sheet keeps
   * its identity instead of turning into a list.
   */
  @media (max-width: 860px) {
    .atlas {
      height: auto;
      min-height: 100dvh;
    }
    .atlas__body {
      grid-template-columns: minmax(0, 1fr);
    }
    .telemetry {
      gap: 0.35rem 0.8rem;
    }
    .telemetry__paths {
      margin-left: 0;
    }
    .rail,
    .index,
    .reader-wrap {
      display: block;
      border-right: 0;
    }
    .rail,
    .reader-wrap {
      border-bottom: 1px solid var(--atlas-rule);
    }
    .plan {
      height: 54vh;
    }
    .index__scroll {
      overflow-y: visible;
    }
    summary {
      display: list-item;
      padding: 0.5rem 0.7rem;
      background: var(--atlas-panel);
      border-top: 1px solid var(--atlas-rule);
      color: var(--atlas-ink);
      font:
        600 11px/1.5 ui-sans-serif,
        system-ui,
        sans-serif;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      cursor: pointer;
    }
  }
</style>
