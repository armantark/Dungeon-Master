<!--
@component
SettingsModal — app-global LLM preset picker.

Surfaces the two backend presets (Kimi, Gemini split) so the player
can swap routing without restarting the server. The backend is the
source of truth: this component only renders what `/settings/llm`
returned and round-trips a `POST /settings/llm` on selection.

Why a one-shot modal instead of inline strip controls:
  Picking a model is rare (typically once per session, often once
  ever) and the trade-offs deserve a few sentences of context — the
  Gemini split is "Flash for tool calls, Pro for prose", which
  doesn't fit on a hamburger label. A modal gives us room for the
  per-preset description and the "missing env vars" diagnostic
  without shrinking either to one line.

The store owns load/save lifecycle (open/close/save) so any future
surface (a status-strip pill, a slash command) can drive this same
UI without prop drilling. We deliberately read `game.settings` /
`game.settingsStatus` directly rather than wiring props because the
modal is a singleton and prop drilling would only obscure the data
flow.

Closing rules: clicking the backdrop, hitting Escape, or pressing
Cancel/Done all close the modal. We do *not* auto-close after a
successful preset swap — the player likely wants to confirm the
"Active preset" readout updated before backing out. A "Done"
button collapses the modal once they've verified.
-->
<script lang="ts">
  import { game } from "../lib/store.svelte";
  import type {
    LLMProviderCredential,
    LLMPreset,
    LLMPresetOption,
  } from "../lib/types";

  let panelRef: HTMLDivElement | null = $state(null);

  // We snapshot the active preset locally so an in-flight save
  // doesn't show the preset as "selected" before the backend has
  // confirmed the swap. Once `settingsStatus` returns to "ready"
  // and `game.settings.preset` reflects the new value, the radio
  // ticks over.
  const activePreset = $derived<LLMPreset | null>(game.settings?.preset ?? null);
  const presets = $derived<LLMPresetOption[]>(game.settings?.presets ?? []);
  const providerCredentials = $derived<LLMProviderCredential[]>(
    game.settings?.provider_credentials ?? [],
  );
  const isSaving = $derived(game.settingsStatus === "saving");
  const isLoading = $derived(
    game.settingsStatus === "loading" && game.settings === null,
  );
  const hasLoadError = $derived(
    game.settingsStatus === "error" && game.settings === null,
  );

  function close(): void {
    if (isSaving) return;
    game.closeSettings();
  }

  async function pick(preset: LLMPreset): Promise<void> {
    if (isSaving) return;
    if (preset === activePreset) return;
    await game.updateLlmPreset(preset);
  }

  function handleKey(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  }

  $effect(() => {
    if (!game.settingsOpen) return;
    window.addEventListener("keydown", handleKey);
    // Focus the dialog on open so subsequent keypresses (Tab, Esc)
    // route to it instead of whatever button opened it.
    panelRef?.focus();
    return () => window.removeEventListener("keydown", handleKey);
  });

  async function retryLoad(): Promise<void> {
    await game.openSettings();
  }
</script>

{#if game.settingsOpen}
  <div
    class="overlay"
    role="presentation"
    onclick={(event) => {
      if (event.target === event.currentTarget) close();
    }}
    onkeydown={() => {
      /* keyboard handled at window level via handleKey */
    }}
  >
    <div
      bind:this={panelRef}
      class="panel parchment deckle"
      role="dialog"
      aria-modal="true"
      aria-labelledby="settings-modal-title"
      aria-describedby="settings-modal-desc"
      tabindex="-1"
    >
      <header class="head">
        <span class="kicker">Configuration</span>
        <h2 id="settings-modal-title">Narrative Model</h2>
        <p id="settings-modal-desc" class="muted desc">
          Choose which LLM stack drives narration, planner routing, and
          mechanical reasoning. The change applies immediately and is
          persisted to <code>data/runtime_settings.json</code>.
        </p>
      </header>

      {#if isLoading}
        <div class="state-row">
          <span class="spinner-row">Loading current preset…</span>
        </div>
      {:else if hasLoadError}
        <div class="state-row error">
          <p>Couldn't load LLM settings: {game.settingsError}</p>
          <button type="button" class="btn" onclick={() => void retryLoad()}>
            Retry
          </button>
        </div>
      {:else}
        {#if game.settings}
          <section class="active iron" aria-label="Active preset readout">
            <span class="kicker">Active</span>
            <dl class="active-models">
              <div>
                <dt>Structured</dt>
                <dd>{game.settings.structured_model}</dd>
              </div>
              <div>
                <dt>Narration</dt>
                <dd>{game.settings.narration_model}</dd>
              </div>
              <div>
                <dt>Reasoning</dt>
                <dd>{game.settings.reasoning_model}</dd>
              </div>
            </dl>
          </section>

          <section class="credentials parchment" aria-label="Provider credentials">
            <span class="kicker">Provider keys</span>
            <ul class="credential-list">
              {#each providerCredentials as credential (credential.id)}
                <li class="credential-row">
                  <div class="credential-copy">
                    <span class="credential-label">{credential.label}</span>
                    <span class="credential-status">
                      {#if credential.configured}
                        {credential.source === "env"
                          ? "Loaded from .env"
                          : "Saved in app settings"}
                        {#if credential.masked_key}
                          <code>{credential.masked_key}</code>
                        {/if}
                      {:else}
                        No key configured yet.
                      {/if}
                    </span>
                  </div>
                  <button
                    type="button"
                    class="btn ghost credential-btn"
                    disabled={isSaving}
                    onclick={() => game.openCredentialSetup(credential.id)}
                  >
                    {credential.configured ? "Update key" : "Add key"}
                  </button>
                </li>
              {/each}
            </ul>
          </section>
        {/if}

        {#if game.settingsSaveError}
          <p class="save-error" role="alert">{game.settingsSaveError}</p>
        {/if}

        <ul class="presets" role="radiogroup" aria-label="LLM presets">
          {#each presets as preset (preset.id)}
            {@const checked = activePreset === preset.id}
            {@const disabled = (!preset.available && !checked) || isSaving}
            <li>
              <button
                type="button"
                role="radio"
                aria-checked={checked}
                class="preset-card"
                class:checked
                class:unavailable={!preset.available && !checked}
                {disabled}
                onclick={() => void pick(preset.id)}
              >
                <header class="preset-head">
                  <span class="preset-tick" aria-hidden="true">
                    {checked ? "●" : "○"}
                  </span>
                  <span class="preset-label">{preset.label}</span>
                  {#if !preset.available}
                    <span class="badge unavailable-badge">Unavailable</span>
                  {:else if checked}
                    <span class="badge active-badge">Active</span>
                  {/if}
                </header>
                <p class="preset-desc">{preset.description}</p>
                <dl class="preset-models">
                  <div>
                    <dt>Structured</dt>
                    <dd>{preset.structured_model}</dd>
                  </div>
                  <div>
                    <dt>Narration</dt>
                    <dd>{preset.narration_model}</dd>
                  </div>
                  <div>
                    <dt>Reasoning</dt>
                    <dd>{preset.reasoning_model}</dd>
                  </div>
                </dl>
                {#if !preset.available && preset.missing_env_vars.length > 0}
                  <p class="missing">
                    Missing environment variables:
                    <code>{preset.missing_env_vars.join(", ")}</code>
                  </p>
                {/if}
              </button>
            </li>
          {/each}
        </ul>
      {/if}

      <footer class="foot">
        <button
          type="button"
          class="btn"
          onclick={close}
          disabled={isSaving}
        >
          {isSaving ? "Saving…" : "Done"}
        </button>
      </footer>
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 100;
    background: color-mix(in oklab, var(--ink-black) 75%, transparent);
    backdrop-filter: blur(2px);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 1rem;
  }
  .panel {
    width: min(640px, 100%);
    max-height: calc(100vh - 2rem);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
    outline: none;
  }
  .head {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }
  .desc {
    margin-bottom: 0;
    font-size: 0.92rem;
    line-height: 1.5;
  }
  .desc code {
    font-family: var(--font-pixel);
    font-size: 0.85em;
    padding: 0.05em 0.3em;
    background: color-mix(in oklab, var(--ink-bruise) 18%, transparent);
    border-radius: 2px;
  }
  .state-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.8rem;
    padding: 0.8rem 0;
  }
  .state-row.error {
    color: color-mix(in oklab, var(--rust-blood) 80%, var(--ink-black));
  }
  .save-error {
    margin: 0;
    padding: 0.55rem 0.7rem;
    background: color-mix(in oklab, var(--rust-blood) 16%, transparent);
    border: 1px solid color-mix(in oklab, var(--rust-blood) 55%, transparent);
    color: color-mix(in oklab, var(--rust-blood) 80%, var(--ink-black));
    font-size: 0.9rem;
    border-radius: 2px;
  }
  .active {
    padding: 0.6rem 0.8rem;
    border-radius: 2px;
  }
  .credentials {
    padding: 0.6rem 0.8rem;
    border-radius: 2px;
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
  }
  .credential-list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.55rem;
  }
  .credential-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.8rem;
    flex-wrap: wrap;
  }
  .credential-copy {
    display: flex;
    flex-direction: column;
    gap: 0.12rem;
    min-width: 0;
  }
  .credential-label {
    font-family: var(--font-display);
    font-size: 0.98rem;
    color: color-mix(in oklab, var(--ink-bruise) 82%, var(--ink-black));
  }
  .credential-status {
    font-size: 0.86rem;
    line-height: 1.4;
    color: color-mix(in oklab, var(--ink-bruise) 76%, var(--ink-black));
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
    align-items: center;
  }
  .credential-status code {
    font-family: var(--font-pixel);
    font-size: 0.84em;
    padding: 0.05em 0.3em;
    background: color-mix(in oklab, var(--ink-bruise) 14%, transparent);
    border-radius: 2px;
  }
  .credential-btn {
    flex-shrink: 0;
  }
  .active-models {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 0.4rem 1rem;
    margin: 0.2rem 0 0 0;
    padding: 0;
  }
  .active-models > div {
    display: flex;
    flex-direction: column;
    gap: 0.05rem;
    min-width: 0;
  }
  .active-models dt {
    font-family: var(--font-pixel);
    font-size: 0.7rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--gold-tarnished);
    margin: 0;
  }
  .active-models dd {
    margin: 0;
    font-family: var(--font-pixel);
    font-size: 0.78rem;
    color: var(--paper-warm);
    overflow-wrap: anywhere;
  }
  .presets {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
  }
  .preset-card {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    width: 100%;
    text-align: left;
    padding: 0.85rem 0.95rem;
    /*
     * The cards inherit the global button reset, but we want them to
     * read like clickable cards on the parchment surface — not like
     * the iron buttons in the rest of the app. Override the gradient
     * with a flat off-paper tone so the radio affordance stays
     * discoverable at a glance.
     */
    background: color-mix(in oklab, var(--paper-bone) 92%, var(--ink-bruise));
    color: var(--ink-deep);
    border: 1px solid color-mix(in oklab, var(--ink-bruise) 45%, transparent);
    border-radius: 3px;
    font-family: var(--font-body);
    text-transform: none;
    letter-spacing: 0;
    transition: border-color 120ms ease, background 120ms ease, transform 120ms ease;
  }
  .preset-card:hover:not(:disabled),
  .preset-card:focus-visible:not(:disabled) {
    border-color: var(--gold-tarnished);
    background: color-mix(in oklab, var(--paper-bone) 88%, var(--gold-tarnished));
    transform: translateY(-1px);
  }
  .preset-card.checked {
    border-color: var(--gold-bright);
    background: color-mix(in oklab, var(--paper-bone) 80%, var(--gold-tarnished));
    box-shadow: inset 0 0 0 1px color-mix(in oklab, var(--gold-bright) 40%, transparent);
  }
  .preset-card.unavailable {
    opacity: 0.65;
    cursor: not-allowed;
  }
  .preset-card:disabled {
    cursor: not-allowed;
  }
  .preset-head {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  .preset-tick {
    font-family: var(--font-pixel);
    font-size: 1rem;
    color: var(--gold-bright);
    width: 1.1rem;
    text-align: center;
  }
  .preset-label {
    font-family: var(--font-display);
    font-size: 1.05rem;
    color: color-mix(in oklab, var(--ink-bruise) 80%, var(--ink-black));
  }
  .badge {
    margin-left: auto;
    font-family: var(--font-pixel);
    font-size: 0.65rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 0.1rem 0.4rem;
    border-radius: 1px;
  }
  .active-badge {
    background: color-mix(in oklab, var(--gold-bright) 70%, transparent);
    color: var(--ink-black);
  }
  .unavailable-badge {
    background: color-mix(in oklab, var(--rust-blood) 60%, transparent);
    color: var(--paper-warm);
  }
  .preset-desc {
    margin: 0;
    font-size: 0.9rem;
    line-height: 1.45;
    color: color-mix(in oklab, var(--ink-bruise) 82%, var(--ink-black));
  }
  .preset-models {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 0.3rem 0.8rem;
    margin: 0;
    padding: 0;
  }
  .preset-models > div {
    display: flex;
    flex-direction: column;
    gap: 0.05rem;
    min-width: 0;
  }
  .preset-models dt {
    font-family: var(--font-pixel);
    font-size: 0.65rem;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: color-mix(in oklab, var(--rust-blood) 70%, var(--ink-black));
    margin: 0;
  }
  .preset-models dd {
    margin: 0;
    font-family: var(--font-pixel);
    font-size: 0.78rem;
    color: color-mix(in oklab, var(--ink-bruise) 78%, var(--ink-black));
    overflow-wrap: anywhere;
  }
  .missing {
    margin: 0;
    font-size: 0.82rem;
    color: color-mix(in oklab, var(--rust-blood) 80%, var(--ink-black));
  }
  .missing code {
    font-family: var(--font-pixel);
    font-size: 0.85em;
    padding: 0.05em 0.3em;
    background: color-mix(in oklab, var(--ink-bruise) 14%, transparent);
    border-radius: 2px;
  }
  .foot {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    padding-top: 0.4rem;
    border-top: 1px solid color-mix(in oklab, var(--ink-bruise) 30%, transparent);
  }
  .spinner-row {
    font-family: var(--font-pixel);
    font-size: 0.85rem;
    letter-spacing: 0.06em;
    color: var(--paper-shadow);
  }
</style>
