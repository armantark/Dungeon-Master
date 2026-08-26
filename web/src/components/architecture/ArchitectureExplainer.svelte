<script lang="ts">
  import {
    ROLE_META,
    type ArchitectureNode,
    type ArchitecturePath,
    type PathStep,
  } from "../../lib/dev-architecture";
  import { ZONES, placementOf, zoneOf } from "../../lib/architecture-layout";

  const REPOSITORY = "https://github.com/armantark/Dungeon-Master/blob/main/";

  const TABS = [
    { id: "what", label: "What it does" },
    { id: "how", label: "How it is built" },
  ] as const;

  let {
    node,
    path,
    step,
    stepNumber,
    isCurrentStep,
  }: {
    node: ArchitectureNode;
    path: ArchitecturePath;
    step: PathStep | undefined;
    stepNumber: number | undefined;
    isCurrentStep: boolean;
  } = $props();

  let tab = $state<(typeof TABS)[number]["id"]>("what");

  const zone = $derived(ZONES.find((candidate) => candidate.id === zoneOf(node.id)));
  const code = $derived(placementOf(node.id)?.code ?? "");
</script>

<aside class="reader" aria-label="Component reading panel">
  <div class="reader__tabs" role="tablist" aria-label="Reading panel view">
    {#each TABS as entry (entry.id)}
      <button
        type="button"
        role="tab"
        id={`reader-tab-${entry.id}`}
        aria-selected={tab === entry.id}
        aria-controls={`reader-panel-${entry.id}`}
        class:active={tab === entry.id}
        onclick={() => (tab = entry.id)}
      >
        {entry.label}
      </button>
    {/each}
  </div>

  <div class="reader__body">
    <p class="reader__where">
      {#if zone}{String(zone.index).padStart(2, "0")} · {zone.label} ·
      {/if}{ROLE_META[node.role].label}
    </p>
    <h2><span class="reader__code">{code}</span>{node.name}</h2>

    <p class="reader__stop" class:reader__stop--current={isCurrentStep}>
      {#if stepNumber !== undefined}
        Stop {stepNumber} of {path.steps.length} on the {path.name} path
      {:else}
        Not a stop on the {path.name} path
      {/if}
    </p>

    {#if tab === "what"}
      <div role="tabpanel" id="reader-panel-what" aria-labelledby="reader-tab-what">
        <p class="reader__lede">{node.responsibility}</p>

        <dl class="reader__io">
          <dt>Receives</dt>
          <dd><mark>{node.input}</mark></dd>
          <dt>Produces</dt>
          <dd><mark>{node.output}</mark></dd>
        </dl>

        {#if step && (step.payload ?? step.detail)}
          <section class="reader__hop">
            <h3>On this hop</h3>
            {#if step.payload}<p class="reader__payload"><mark>{step.payload}</mark></p>{/if}
            {#if step.detail}<p>{step.detail}</p>{/if}
          </section>
        {/if}
      </div>
    {:else}
      <div role="tabpanel" id="reader-panel-how" aria-labelledby="reader-tab-how">
        <section>
          <h3>Why this boundary exists</h3>
          <p>{node.rationale}</p>
        </section>

        {#if zone}
          <section>
            <h3>Section</h3>
            <p><mark>{zone.label}</mark> — {zone.detail}</p>
          </section>
        {/if}

        <section>
          <h3>Source</h3>
          <ul class="reader__sources">
            {#each node.citations as citation (citation.file + citation.line)}
              <li>
                <a
                  href={`${REPOSITORY}${citation.file}#L${citation.line}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {citation.file}:{citation.line}
                </a>
              </li>
            {/each}
          </ul>
        </section>
      </div>
    {/if}
  </div>
</aside>

<style>
  .reader {
    display: grid;
    grid-template-rows: auto minmax(0, 1fr);
    min-width: 0;
    min-height: 0;
    background: var(--atlas-panel);
    border-left: 1px solid var(--atlas-rule);
  }

  .reader__tabs {
    display: flex;
    border-bottom: 1px solid var(--atlas-rule);
  }
  .reader__tabs button {
    flex: 1 1 0;
    padding: 0.45rem 0.5rem;
    color: var(--atlas-ink-soft);
    background: transparent;
    border: 0;
    border-right: 1px solid var(--atlas-rule);
    border-radius: 0;
    box-shadow: none;
    text-shadow: none;
    font:
      600 11.5px/1.4 ui-sans-serif,
      system-ui,
      sans-serif;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    cursor: pointer;
  }
  .reader__tabs button::before {
    display: none;
  }
  .reader__tabs button:last-child {
    border-right: 0;
  }
  .reader__tabs button:hover {
    color: var(--atlas-ink);
    filter: none;
  }
  .reader__tabs button.active {
    color: var(--atlas-paper);
    background: var(--atlas-ink);
  }

  .reader__body {
    min-height: 0;
    padding: 0.8rem 0.9rem 1.4rem;
    overflow-y: auto;
    color: var(--atlas-ink-body);
    font:
      13.5px/1.5 ui-sans-serif,
      system-ui,
      sans-serif;
  }

  .reader__where {
    margin: 0;
    color: var(--atlas-ink-soft);
    font:
      600 10.5px/1.5 ui-sans-serif,
      system-ui,
      sans-serif;
    letter-spacing: 0.09em;
    text-transform: uppercase;
  }

  h2 {
    display: flex;
    align-items: baseline;
    gap: 0.4rem;
    margin: 0.15rem 0 0.3rem;
    color: var(--atlas-ink);
    font:
      600 17px/1.2 ui-sans-serif,
      system-ui,
      sans-serif;
    letter-spacing: -0.01em;
  }
  .reader__code {
    flex: 0 0 auto;
    padding: 0.05rem 0.24rem;
    color: var(--atlas-paper);
    background: var(--atlas-ink);
    font:
      600 11px/1.35 ui-monospace,
      SFMono-Regular,
      Menlo,
      Consolas,
      monospace;
    letter-spacing: 0.06em;
  }

  h3 {
    margin: 0 0 0.2rem;
    color: var(--atlas-ink);
    font:
      600 10.5px/1.5 ui-sans-serif,
      system-ui,
      sans-serif;
    letter-spacing: 0.09em;
    text-transform: uppercase;
  }

  .reader__stop {
    margin: 0 0 0.7rem;
    padding-bottom: 0.6rem;
    border-bottom: 1px solid var(--atlas-rule);
    color: var(--atlas-ink-soft);
    font:
      600 11.5px/1.4 ui-sans-serif,
      system-ui,
      sans-serif;
  }
  .reader__stop--current {
    color: var(--atlas-ink);
  }

  .reader__lede {
    margin: 0;
  }

  .reader__io {
    display: grid;
    grid-template-columns: 4.6rem minmax(0, 1fr);
    gap: 0.25rem 0.6rem;
    margin: 0.8rem 0 0;
  }
  .reader__io dt {
    color: var(--atlas-ink);
    font:
      600 10.5px/1.7 ui-sans-serif,
      system-ui,
      sans-serif;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .reader__io dd {
    margin: 0;
    min-width: 0;
  }

  mark {
    padding: 0 0.15rem;
    color: var(--atlas-ink);
    background: var(--atlas-highlight);
    font:
      12.5px/1.45 ui-monospace,
      SFMono-Regular,
      Menlo,
      Consolas,
      monospace;
    overflow-wrap: anywhere;
  }

  section {
    margin-top: 0.95rem;
  }
  section p {
    margin: 0;
  }

  .reader__hop {
    padding: 0.55rem 0.6rem;
    background: color-mix(in srgb, var(--atlas-ink) 6%, transparent);
    border-left: 2px solid var(--atlas-ink);
  }
  .reader__payload {
    margin: 0 0 0.35rem;
  }

  .reader__sources {
    display: grid;
    gap: 0.2rem;
    margin: 0;
    padding: 0;
    list-style: none;
  }
  .reader__sources a {
    color: var(--atlas-ink);
    font:
      12px/1.45 ui-monospace,
      SFMono-Regular,
      Menlo,
      Consolas,
      monospace;
    text-decoration-thickness: 1px;
    text-underline-offset: 2px;
    overflow-wrap: anywhere;
  }
  .reader__sources a:hover {
    background: var(--atlas-highlight);
  }
  .reader__sources a:focus-visible {
    outline: 2px solid var(--atlas-ink);
    outline-offset: 2px;
  }
</style>
