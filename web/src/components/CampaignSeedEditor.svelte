<!--
@component
CampaignSeedEditor — F-15 pre-campaign setting and difficulty editor.

Why this lives above the CharacterSetup mode picker rather than in
its own modal:
  - The seed steers character generation. Templates, the assist quiz,
    and the eventual "Start campaign" generation all read
    `state.campaign_seed`, so committing it before the player picks a
    creation path keeps the LLM from contradicting itself between
    "what kind of survivor" and "what kind of world".
  - We deliberately don't auto-save on every keystroke. The editor
    keeps a local draft, and "Apply settings" sends one POST. Each
    POST regenerates state-derived prompts on the backend, so chatty
    saves would burn tokens on a player who is just exploring the
    sliders.
  - Once the campaign is `active` (or `ended`), the seed is locked.
    The component still renders a read-only summary so the inspector
    surface always has something to show, but the editor controls
    are hidden — re-rolling a campaign's setting after the world is
    drawn would silently desync the canon.
-->
<script lang="ts">
  import { untrack } from "svelte";
  import { game } from "../lib/store.svelte";
  import {
    ADVANTAGE_PAYOFF_LABEL,
    CAMPAIGN_SEED_PRESETS,
    DANGER_PROFILE_BLURB,
    DANGER_PROFILE_LABEL,
    GENRE_LABEL,
    MAGIC_LEVEL_LABEL,
    seedBadgeLabel,
    seedsEqual,
    STAKES_SCALE_LABEL,
    TECH_LEVEL_LABEL,
    TIME_PERIOD_LABEL,
    TONE_DARK_BRIGHT_LABEL,
    TONE_GRIM_NOBLE_LABEL,
  } from "../lib/campaign-seed";
  import type {
    CampaignDangerProfile,
    CampaignGenre,
    CampaignMagicLevel,
    CampaignSeed,
    CampaignStakesScale,
    CampaignTechLevel,
    CampaignTimePeriod,
    CampaignToneDarkBright,
    CampaignToneGrimNoble,
  } from "../lib/types";

  type Props = {
    seed: CampaignSeed;
    locked: boolean;
  };
  const { seed, locked }: Props = $props();

  // Local draft so the player can scrub the sliders without each tick
  // hitting the backend. We rebase on the persisted seed every time
  // the props update — that's the sync we want when another path
  // committed a seed (e.g. picking a preset reloaded GameState). The
  // initial structuredClone is wrapped in `untrack` because the
  // canonical sync source is the $effect below; tying the runes
  // initializer to `seed` would create a duplicate dependency that
  // Svelte (correctly) warns about.
  let draft: CampaignSeed = $state(untrack(() => structuredClone(seed)));
  let expanded: boolean = $state(false);

  $effect(() => {
    // Re-sync whenever the canonical seed changes. Avoid clobbering
    // the player's in-progress edits if the only diff is something
    // they already typed — but since we apply on explicit commit,
    // the canonical seed only changes after we POST, so a hard
    // overwrite is the right call.
    draft = structuredClone(seed);
  });

  const dirty = $derived(!seedsEqual(draft, seed));
  const isSaving = $derived(game.isLoading);

  const TIME_PERIOD_KEYS: CampaignTimePeriod[] = Object.keys(
    TIME_PERIOD_LABEL,
  ) as CampaignTimePeriod[];
  const TONE_GRIM_KEYS: CampaignToneGrimNoble[] = Object.keys(
    TONE_GRIM_NOBLE_LABEL,
  ) as CampaignToneGrimNoble[];
  const TONE_DARK_KEYS: CampaignToneDarkBright[] = Object.keys(
    TONE_DARK_BRIGHT_LABEL,
  ) as CampaignToneDarkBright[];
  const DANGER_KEYS: CampaignDangerProfile[] = Object.keys(
    DANGER_PROFILE_LABEL,
  ) as CampaignDangerProfile[];
  const GENRE_KEYS: CampaignGenre[] = Object.keys(GENRE_LABEL) as CampaignGenre[];
  const MAGIC_KEYS: CampaignMagicLevel[] = Object.keys(
    MAGIC_LEVEL_LABEL,
  ) as CampaignMagicLevel[];
  const TECH_KEYS: CampaignTechLevel[] = Object.keys(
    TECH_LEVEL_LABEL,
  ) as CampaignTechLevel[];
  const STAKES_KEYS: CampaignStakesScale[] = Object.keys(
    STAKES_SCALE_LABEL,
  ) as CampaignStakesScale[];

  // Cap genre selection at three — the backend enforces the same
  // bound (`max_length=3`). Toggling beyond that is a no-op so we
  // don't surface a "save failed" message for what is clearly a
  // user-side limit.
  const GENRE_CAP = 3;

  function pickPreset(presetId: string): void {
    if (locked) return;
    const preset = CAMPAIGN_SEED_PRESETS.find((p) => p.id === presetId);
    if (preset === undefined) return;
    draft = structuredClone(preset.seed);
  }

  function toggleGenre(genre: CampaignGenre): void {
    if (locked) return;
    if (draft.genres.includes(genre)) {
      // Don't let the player remove the last genre — backend rejects
      // an empty list and rebases to dark_fantasy. Keeping at least
      // one selected mirrors that constraint visibly.
      if (draft.genres.length === 1) return;
      draft = { ...draft, genres: draft.genres.filter((g) => g !== genre) };
      return;
    }
    if (draft.genres.length >= GENRE_CAP) return;
    draft = { ...draft, genres: [...draft.genres, genre] };
  }

  // Picking a built-in preset sets the `preset` string verbatim.
  // Hand-editing any field doesn't auto-rename — but we surface a
  // "Custom" tag in the strip so the player understands what they
  // committed last.
  const presetMatch = $derived(
    CAMPAIGN_SEED_PRESETS.find((p) => seedsEqual(p.seed, draft)) ?? null,
  );
  const draftPresetLabel = $derived(presetMatch?.label ?? draft.preset);

  function renamePreset(label: string): void {
    if (locked) return;
    draft = { ...draft, preset: label };
  }

  async function applyDraft(): Promise<void> {
    if (locked || !dirty || isSaving) return;
    await game.updateCampaignSeed(draft);
  }

  function discardDraft(): void {
    if (locked || !dirty) return;
    draft = structuredClone(seed);
  }

  // Summary strip readout: a one-liner that always shows what the
  // *committed* seed is, regardless of dirty edits. The expanded
  // editor has its own "draft preview" line.
  const committedBadge = $derived(seedBadgeLabel(seed));
  const committedDanger = $derived(DANGER_PROFILE_LABEL[seed.danger_profile]);
  const committedDangerBlurb = $derived(DANGER_PROFILE_BLURB[seed.danger_profile]);
</script>

<section class="seed iron" aria-labelledby="seed-title">
  <header class="seed__head">
    <div class="seed__title">
      <span class="kicker">Campaign Setting</span>
      <h3 id="seed-title">{committedBadge}</h3>
    </div>
    <div class="seed__head-controls">
      {#if locked}
        <span class="locked pixel" title="The campaign has started — the seed is locked.">
          Locked
        </span>
      {:else}
        <button
          type="button"
          class="ghost expand"
          onclick={() => (expanded = !expanded)}
          aria-expanded={expanded}
        >
          {expanded ? "Hide details" : "Edit settings"}
        </button>
      {/if}
    </div>
  </header>

  <p class="seed__danger-line">
    <span class="pixel danger danger--{seed.danger_profile}">{committedDanger}</span>
    <span class="muted">{committedDangerBlurb}</span>
  </p>

  {#if !locked && expanded}
    <div class="editor">
      <div class="presets">
        <span class="kicker">Presets</span>
        <div class="preset-grid">
          {#each CAMPAIGN_SEED_PRESETS as preset (preset.id)}
            {@const isActive = presetMatch?.id === preset.id}
            <button
              type="button"
              class="preset-card"
              class:preset-card--active={isActive}
              onclick={() => pickPreset(preset.id)}
              disabled={isSaving}
            >
              <strong>{preset.label}</strong>
              <span class="muted small">{preset.blurb}</span>
            </button>
          {/each}
        </div>
      </div>

      <div class="grid">
        <fieldset class="field">
          <legend><span class="kicker">Difficulty</span></legend>
          <div class="radio-row">
            {#each DANGER_KEYS as danger (danger)}
              <label class="chip" class:chip--active={draft.danger_profile === danger}>
                <input
                  type="radio"
                  name="danger"
                  value={danger}
                  checked={draft.danger_profile === danger}
                  onchange={() => (draft = { ...draft, danger_profile: danger })}
                  disabled={isSaving}
                />
                <span class="pixel">{DANGER_PROFILE_LABEL[danger]}</span>
              </label>
            {/each}
          </div>
          <p class="hint">{DANGER_PROFILE_BLURB[draft.danger_profile]}</p>
        </fieldset>

        <fieldset class="field">
          <legend><span class="kicker">Era</span></legend>
          <select
            value={draft.time_period}
            onchange={(e) =>
              (draft = {
                ...draft,
                time_period: (e.currentTarget as HTMLSelectElement)
                  .value as CampaignTimePeriod,
              })}
            disabled={isSaving}
          >
            {#each TIME_PERIOD_KEYS as key (key)}
              <option value={key}>{TIME_PERIOD_LABEL[key]}</option>
            {/each}
          </select>
        </fieldset>

        <fieldset class="field">
          <legend><span class="kicker">Tone — Grim · Noble</span></legend>
          <div class="radio-row">
            {#each TONE_GRIM_KEYS as key (key)}
              <label class="chip" class:chip--active={draft.tone_grim_noble === key}>
                <input
                  type="radio"
                  name="tone-grim"
                  value={key}
                  checked={draft.tone_grim_noble === key}
                  onchange={() => (draft = { ...draft, tone_grim_noble: key })}
                  disabled={isSaving}
                />
                <span>{TONE_GRIM_NOBLE_LABEL[key]}</span>
              </label>
            {/each}
          </div>
        </fieldset>

        <fieldset class="field">
          <legend><span class="kicker">Tone — Dark · Bright</span></legend>
          <div class="radio-row">
            {#each TONE_DARK_KEYS as key (key)}
              <label class="chip" class:chip--active={draft.tone_dark_bright === key}>
                <input
                  type="radio"
                  name="tone-dark"
                  value={key}
                  checked={draft.tone_dark_bright === key}
                  onchange={() => (draft = { ...draft, tone_dark_bright: key })}
                  disabled={isSaving}
                />
                <span>{TONE_DARK_BRIGHT_LABEL[key]}</span>
              </label>
            {/each}
          </div>
        </fieldset>

        <fieldset class="field field--wide">
          <legend>
            <span class="kicker">Genres</span>
            <span class="muted small">Pick up to {GENRE_CAP}</span>
          </legend>
          <div class="genre-row">
            {#each GENRE_KEYS as key (key)}
              {@const selected = draft.genres.includes(key)}
              {@const disabled =
                isSaving
                || (!selected && draft.genres.length >= GENRE_CAP)
                || (selected && draft.genres.length === 1)}
              <label
                class="chip"
                class:chip--active={selected}
                class:chip--disabled={disabled}
              >
                <input
                  type="checkbox"
                  checked={selected}
                  disabled={disabled}
                  onchange={() => toggleGenre(key)}
                />
                <span>{GENRE_LABEL[key]}</span>
              </label>
            {/each}
          </div>
        </fieldset>

        <fieldset class="field">
          <legend><span class="kicker">Magic</span></legend>
          <select
            value={draft.magic_level}
            onchange={(e) =>
              (draft = {
                ...draft,
                magic_level: (e.currentTarget as HTMLSelectElement)
                  .value as CampaignMagicLevel,
              })}
            disabled={isSaving}
          >
            {#each MAGIC_KEYS as key (key)}
              <option value={key}>{MAGIC_LEVEL_LABEL[key]}</option>
            {/each}
          </select>
        </fieldset>

        <fieldset class="field">
          <legend><span class="kicker">Technology</span></legend>
          <select
            value={draft.tech_level}
            onchange={(e) =>
              (draft = {
                ...draft,
                tech_level: (e.currentTarget as HTMLSelectElement)
                  .value as CampaignTechLevel,
              })}
            disabled={isSaving}
          >
            {#each TECH_KEYS as key (key)}
              <option value={key}>{TECH_LEVEL_LABEL[key]}</option>
            {/each}
          </select>
        </fieldset>

        <fieldset class="field">
          <legend><span class="kicker">Stakes</span></legend>
          <select
            value={draft.stakes_scale}
            onchange={(e) =>
              (draft = {
                ...draft,
                stakes_scale: (e.currentTarget as HTMLSelectElement)
                  .value as CampaignStakesScale,
              })}
            disabled={isSaving}
          >
            {#each STAKES_KEYS as key (key)}
              <option value={key}>{STAKES_SCALE_LABEL[key]}</option>
            {/each}
          </select>
        </fieldset>

        <fieldset class="field field--wide">
          <legend><span class="kicker">Preset name</span></legend>
          <input
            type="text"
            value={draft.preset}
            oninput={(e) => renamePreset((e.currentTarget as HTMLInputElement).value)}
            disabled={isSaving}
            placeholder="Free-text label for the save library"
          />
        </fieldset>

        <fieldset class="field field--wide">
          <legend><span class="kicker">Inspirations (flavor only)</span></legend>
          <textarea
            rows="2"
            value={draft.inspirations}
            oninput={(e) =>
              (draft = {
                ...draft,
                inspirations: (e.currentTarget as HTMLTextAreaElement).value,
              })}
            disabled={isSaving}
            placeholder="e.g. Berserk + Dark Souls + Fear & Hunger"
          ></textarea>
          <p class="hint muted small">
            The model uses these as flavor cues only. Named characters,
            locations, factions, and lore from inspirations are never
            copied verbatim.
          </p>
        </fieldset>

        <fieldset class="field field--wide">
          <legend><span class="kicker">Restrictions</span></legend>
          <textarea
            rows="2"
            value={draft.restrictions}
            oninput={(e) =>
              (draft = {
                ...draft,
                restrictions: (e.currentTarget as HTMLTextAreaElement).value,
              })}
            disabled={isSaving}
            placeholder="e.g. No modern slang. No grimdark cliché names."
          ></textarea>
        </fieldset>
      </div>

      <footer class="actions">
        <p class="muted small">
          {#if dirty}
            Draft: <strong>{draftPresetLabel}</strong> · {DANGER_PROFILE_LABEL[draft.danger_profile]}
          {:else}
            Settings match the saved seed.
          {/if}
        </p>
        <div class="actions__buttons">
          <button class="ghost" onclick={discardDraft} disabled={!dirty || isSaving}>
            Reset
          </button>
          <button onclick={applyDraft} disabled={!dirty || isSaving}>
            {isSaving ? "Saving…" : "Apply settings"}
          </button>
        </div>
      </footer>
    </div>
  {/if}
</section>

<!--
  F-18 reference card (read-only). We render a tiny legend of the
  fictional-advantage payoffs at the bottom of the editor so the
  player knows the menu of mechanical levers their setups can
  resolve into. Keeping it next to the difficulty knob frames F-18
  as "what difficulty looks like in your hands" rather than
  "another submenu".
-->
{#if !locked}
  <details class="advantage-legend">
    <summary class="kicker">Combat: fictional advantages</summary>
    <p class="muted small">
      Setup actions (blinding, hamstringing, exposing a weakness, etc.)
      are resolved by Cairn 2e mechanics rather than freeform damage.
      Each setup commits to one of these payoffs when consumed by the
      next attack:
    </p>
    <ul class="payoff-list">
      {#each Object.keys(ADVANTAGE_PAYOFF_LABEL) as key (key)}
        <li>
          <span class="pixel">{ADVANTAGE_PAYOFF_LABEL[key as keyof typeof ADVANTAGE_PAYOFF_LABEL]}</span>
        </li>
      {/each}
    </ul>
  </details>
{/if}

<style>
  .seed {
    padding: 1rem 1.1rem;
    display: grid;
    gap: 0.6rem;
  }
  .seed__head {
    display: flex;
    align-items: flex-end;
    justify-content: space-between;
    gap: 0.7rem;
    flex-wrap: wrap;
  }
  .seed__title {
    display: grid;
    gap: 0.2rem;
  }
  .seed__title h3 {
    margin: 0;
    font-size: 1.2rem;
    color: var(--paper-warm);
  }
  .seed__head-controls {
    display: flex;
    gap: 0.4rem;
  }
  .locked {
    padding: 0.18rem 0.45rem;
    border: 1px solid var(--gold-tarnished);
    color: var(--gold-tarnished);
    font-size: 0.7rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  .seed__danger-line {
    margin: 0;
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    flex-wrap: wrap;
    font-size: 0.92rem;
  }
  .danger {
    padding: 0.16rem 0.45rem;
    border: 1px solid currentColor;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-size: 0.7rem;
  }
  /*
   * Mirror the danger semantic in the chip color so a player can
   * scan the rail without reading the label: gold for the easier
   * tiers, rust for harsher, blood for lethal. The match is
   * intentional with the foe-tier coloring on the combat tracker.
   */
  .danger--story {
    color: color-mix(in oklab, var(--gold-bright) 70%, var(--paper-bone));
  }
  .danger--standard {
    color: var(--gold-tarnished);
  }
  .danger--harsh {
    color: var(--rust-iron);
  }
  .danger--lethal {
    color: var(--rust-blood);
  }

  .editor {
    display: grid;
    gap: 0.85rem;
    border-top: var(--rule-hair);
    padding-top: 0.8rem;
  }

  .presets {
    display: grid;
    gap: 0.4rem;
  }
  .preset-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
    gap: 0.5rem;
  }
  .preset-card {
    text-align: left;
    padding: 0.55rem 0.7rem;
    display: grid;
    gap: 0.2rem;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 35%, transparent);
    background: color-mix(in oklab, var(--ink-deep) 80%, transparent);
    cursor: pointer;
    text-transform: none;
    letter-spacing: 0;
    color: var(--paper-bone);
  }
  .preset-card strong {
    font-family: var(--font-display);
    color: var(--paper-warm);
    font-weight: 400;
  }
  .preset-card:hover:not(:disabled) {
    border-color: var(--gold-tarnished);
  }
  .preset-card--active {
    border-color: var(--gold-bright);
    background: color-mix(in oklab, var(--gold-tarnished) 14%, var(--ink-deep) 86%);
  }
  .small {
    font-size: 0.84rem;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 0.7rem;
  }
  .field {
    margin: 0;
    padding: 0.55rem 0.6rem 0.6rem;
    border: var(--rule-hair);
    display: grid;
    gap: 0.4rem;
  }
  .field--wide {
    grid-column: 1 / -1;
  }
  .field legend {
    display: flex;
    align-items: baseline;
    gap: 0.45rem;
    padding: 0 0.3rem;
  }
  .field select,
  .field input[type="text"],
  .field textarea {
    width: 100%;
  }
  .radio-row,
  .genre-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.28rem 0.55rem;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 30%, transparent);
    border-radius: 2px;
    background: color-mix(in oklab, var(--ink-deep) 80%, transparent);
    cursor: pointer;
    font-size: 0.86rem;
  }
  .chip:hover:not(.chip--disabled) {
    border-color: var(--gold-tarnished);
  }
  .chip--active {
    border-color: var(--gold-bright);
    background: color-mix(in oklab, var(--gold-tarnished) 14%, var(--ink-deep) 86%);
    color: var(--paper-warm);
  }
  .chip--disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .chip input {
    margin: 0;
  }
  .hint {
    margin: 0;
    color: var(--paper-shadow);
    font-size: 0.85rem;
  }

  .actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.7rem;
    border-top: var(--rule-hair);
    padding-top: 0.7rem;
    flex-wrap: wrap;
  }
  .actions p {
    margin: 0;
  }
  .actions__buttons {
    display: flex;
    gap: 0.5rem;
  }

  .advantage-legend {
    margin-top: 0.4rem;
    padding: 0.55rem 0.8rem;
    border-left: 2px solid color-mix(in oklab, var(--gold-tarnished) 50%, transparent);
    background: color-mix(in oklab, var(--ink-deep) 86%, transparent);
  }
  .advantage-legend > summary {
    cursor: pointer;
    color: var(--gold-tarnished);
  }
  .advantage-legend p {
    margin: 0.4rem 0 0.3rem;
  }
  .payoff-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
  }
  .payoff-list li {
    padding: 0.2rem 0.5rem;
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 35%, transparent);
    color: var(--paper-bone);
    font-size: 0.78rem;
  }
  .muted {
    color: var(--paper-shadow);
  }
</style>
