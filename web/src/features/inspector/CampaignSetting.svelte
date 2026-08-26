<script lang="ts">
  import {
    DANGER_PROFILE_BLURB,
    DANGER_PROFILE_LABEL,
    GENRE_LABEL,
    MAGIC_LEVEL_LABEL,
    STAKES_SCALE_LABEL,
    TECH_LEVEL_LABEL,
    TIME_PERIOD_LABEL,
    TONE_DARK_BRIGHT_LABEL,
    TONE_GRIM_NOBLE_LABEL,
    seedBadgeLabel,
  } from "../../lib/campaign-seed";
  import type { CampaignSeed } from "../../lib/types";

  const { seed }: { seed: CampaignSeed } = $props();
</script>

<div class="seed-readout">
  <p class="seed-readout__head pixel">{seedBadgeLabel(seed)}</p>
  <p class="muted seed-readout__danger">{DANGER_PROFILE_BLURB[seed.danger_profile]}</p>
  <dl class="seed-readout__grid">
    <dt>Era</dt>
    <dd>{TIME_PERIOD_LABEL[seed.time_period]}</dd>
    <dt>Tone</dt>
    <dd>
      {TONE_GRIM_NOBLE_LABEL[seed.tone_grim_noble]} · {TONE_DARK_BRIGHT_LABEL[
        seed.tone_dark_bright
      ]}
    </dd>
    <dt>Difficulty</dt>
    <dd class="pixel">{DANGER_PROFILE_LABEL[seed.danger_profile]}</dd>
    <dt>Genres</dt>
    <dd>{seed.genres.map((genre) => GENRE_LABEL[genre]).join(", ")}</dd>
    <dt>Magic</dt>
    <dd>{MAGIC_LEVEL_LABEL[seed.magic_level]}</dd>
    <dt>Tech</dt>
    <dd>{TECH_LEVEL_LABEL[seed.tech_level]}</dd>
    <dt>Stakes</dt>
    <dd>{STAKES_SCALE_LABEL[seed.stakes_scale]}</dd>
    {#if seed.inspirations.trim() !== ""}
      <dt>Inspirations</dt>
      <dd>{seed.inspirations}</dd>
    {/if}
    {#if seed.restrictions.trim() !== ""}
      <dt>Restrictions</dt>
      <dd>{seed.restrictions}</dd>
    {/if}
  </dl>
</div>

<style>
  .seed-readout {
    display: grid;
    gap: 0.5rem;
  }
  .seed-readout__head {
    margin: 0;
    color: var(--gold-bright);
    font-size: 0.92rem;
    letter-spacing: 0.04em;
  }
  .seed-readout__danger {
    margin: 0;
    font-size: 0.85rem;
    line-height: 1.4;
  }
  .seed-readout__grid {
    margin: 0;
    display: grid;
    grid-template-columns: max-content 1fr;
    column-gap: 0.85rem;
    row-gap: 0.25rem;
    font-size: 0.88rem;
  }
  dt {
    margin: 0;
    font-family: var(--font-pixel);
    font-size: 0.7rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--gold-tarnished);
  }
  dd {
    margin: 0;
    color: var(--paper-bone);
  }
</style>
