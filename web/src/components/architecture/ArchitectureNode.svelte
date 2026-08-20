<script lang="ts">
  import { Handle, Position } from "@xyflow/svelte";

  interface ArchNodeData {
    name: string;
    roleLabel: string;
    color: string;
    active: boolean;
    selected: boolean;
    step?: number;
    id: string;
    onSelect: (id: string) => void;
  }

  let { data }: { data: ArchNodeData } = $props();
</script>

<div class="arch-node-shell" style={`--role:${data.color}`}>
  <Handle type="target" position={Position.Left} isConnectable={false} aria-hidden="true" />
  <button
    type="button"
    class="arch-node"
    class:arch-node--dimmed={!data.active}
    class:arch-node--selected={data.selected}
    aria-pressed={data.selected}
    onclick={() => data.onSelect(data.id)}
  >
    {#if data.step !== undefined}
      <span class="arch-node__step" aria-label={`step ${data.step}`}>{data.step}</span>
    {/if}
    <strong class="arch-node__name">{data.name}</strong>
    <span class="arch-node__role">{data.roleLabel}</span>
  </button>
  <Handle type="source" position={Position.Right} isConnectable={false} aria-hidden="true" />
</div>

<style>
  .arch-node-shell {
    width: 100%;
    height: 100%;
  }
  .arch-node {
    position: relative;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 0.15rem;
    width: 100%;
    height: 100%;
    padding: 0.55rem 0.8rem;
    background: #16120d;
    border: 3px solid var(--role);
    color: var(--paper-bone);
    box-shadow: 0 6px 14px rgba(0, 0, 0, 0.55);
    transition: opacity 160ms ease, filter 160ms ease;
    text-align: left;
    cursor: pointer;
    font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    text-transform: none;
  }
  .arch-node--dimmed {
    opacity: 0.42;
    filter: saturate(0.4);
  }
  .arch-node--selected {
    outline: 3px solid var(--gold-bright);
    outline-offset: 2px;
    opacity: 1;
    filter: none;
  }
  .arch-node__name {
    font-size: 20px;
    line-height: 1.2;
    font-weight: 600;
    color: var(--paper-warm);
  }
  .arch-node__role {
    font-size: 16px;
    line-height: 1.2;
    color: color-mix(in srgb, var(--role) 55%, #e8dfc8);
  }
  .arch-node__step {
    position: absolute;
    top: -14px;
    right: -10px;
    display: grid;
    place-items: center;
    width: 28px;
    height: 28px;
    border-radius: 50%;
    background: #3b2d12;
    border: 2px solid var(--gold-bright);
    color: #ffe39b;
    font-family: var(--font-pixel);
    font-size: 16px;
  }
  @media (prefers-reduced-motion: reduce) {
    .arch-node { transition: none; }
  }
</style>
