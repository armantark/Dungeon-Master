<script lang="ts">
  interface RegionData {
    label: string;
    sub: string;
    tint: string;
  }

  let { data }: { data: RegionData } = $props();
</script>

<div class="region" style={`--tint:${data.tint}`}>
  <div class="region__head">
    <strong>{data.label}</strong>
    <span>{data.sub}</span>
  </div>
</div>

<style>
  .region {
    width: 100%;
    height: 100%;
    border: 2px solid var(--tint);
    background: color-mix(in srgb, var(--tint) 7%, #0d0b08);
    box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.6);
  }
  .region__head {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 0.35rem 0.75rem;
    padding: 0.5rem 0.8rem;
    border-bottom: 1px solid color-mix(in srgb, var(--tint) 60%, transparent);
    background: color-mix(in srgb, var(--tint) 14%, #0d0b08);
  }
  .region__head strong {
    font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-weight: 750;
    font-size: 16px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: color-mix(in srgb, var(--tint) 45%, #f2e8d0);
  }
  .region__head span {
    font-size: 16px;
    color: color-mix(in srgb, var(--tint) 30%, #cfc4aa);
  }
</style>
