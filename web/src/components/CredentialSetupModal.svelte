<!--
@component
CredentialSetupModal — first-run and manual BYOK entry surface.

Why a dedicated modal instead of folding key entry into SettingsModal:
  First-run bootstrap must block the rest of the app until at least one
  provider key exists, while later "update my key" flows are optional. A
  dedicated surface lets the runtime gate reuse the same form without
  overloading the preset-picker with required setup logic.
-->
<script lang="ts">
  import { game } from "../lib/store.svelte";
  import type { LLMProvider, LLMProviderCredential } from "../lib/types";

  let panelRef: HTMLDivElement | null = $state(null);
  let apiKey = $state("");
  let provider: LLMProvider = $state("openrouter");

  const open = $derived(game.runtimeStatus === "needs_key" || game.credentialSetupOpen);
  const isRequired = $derived(game.runtimeStatus === "needs_key");
  const isSaving = $derived(game.credentialSetupStatus === "saving");
  const providerCredentials = $derived.by<LLMProviderCredential[]>(() => {
    if (game.settings !== null) return game.settings.provider_credentials;
    return [
      {
        id: "openrouter",
        label: "OpenRouter",
        configured: false,
        source: "none",
        masked_key: null,
      },
      {
        id: "gemini",
        label: "Gemini",
        configured: false,
        source: "none",
        masked_key: null,
      },
    ];
  });

  function close(): void {
    if (isRequired || isSaving) return;
    game.closeCredentialSetup();
  }

  async function submit(): Promise<void> {
    const ok = await game.saveLlmCredentials(provider, apiKey);
    if (ok) apiKey = "";
  }

  function handleKey(event: KeyboardEvent): void {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    }
  }

  $effect(() => {
    if (!open) return;
    provider = game.credentialSetupProvider;
    apiKey = "";
    window.addEventListener("keydown", handleKey);
    panelRef?.focus();
    return () => window.removeEventListener("keydown", handleKey);
  });
</script>

{#if open}
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
      aria-labelledby="credential-setup-title"
      tabindex="-1"
    >
      <header class="head">
        <span class="kicker">Bring Your Own Key</span>
        <h2 id="credential-setup-title">Connect a model provider</h2>
        <p class="muted desc">
          Enter a Gemini or OpenRouter API key to enable AI-driven setup and play.
          This beta stores the key in the app's local config on this machine; your
          existing terminal <code>.env</code> flow still works unchanged.
        </p>
      </header>

      <section class="providers">
        <span class="kicker">Provider</span>
        <div class="provider-grid" role="radiogroup" aria-label="Model provider">
          {#each providerCredentials as credential (credential.id)}
            <button
              type="button"
              class="provider-card"
              class:selected={provider === credential.id}
              aria-pressed={provider === credential.id}
              disabled={isSaving}
              onclick={() => {
                provider = credential.id;
              }}
            >
              <span class="provider-name">{credential.label}</span>
              <span class="provider-status">
                {#if credential.configured}
                  {credential.source === "env" ? "Loaded from .env" : "Saved in app settings"}
                  {#if credential.masked_key}
                    <code>{credential.masked_key}</code>
                  {/if}
                {:else}
                  No key configured yet.
                {/if}
              </span>
            </button>
          {/each}
        </div>
      </section>

      <label class="field">
        <span class="field-label">API key</span>
        <input
          bind:value={apiKey}
          type="password"
          autocomplete="off"
          spellcheck="false"
          placeholder={provider === "gemini"
            ? "Paste a Gemini key"
            : "Paste an OpenRouter key"}
          disabled={isSaving}
        />
      </label>

      {#if game.credentialSetupError}
        <p class="error" role="alert">{game.credentialSetupError}</p>
      {/if}

      <footer class="foot">
        {#if !isRequired}
          <button type="button" class="btn ghost" onclick={close} disabled={isSaving}>
            Cancel
          </button>
        {/if}
        <button type="button" class="btn" onclick={() => void submit()} disabled={isSaving}>
          {isSaving ? "Saving…" : "Save key"}
        </button>
      </footer>
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed;
    inset: 0;
    z-index: 110;
    background: color-mix(in oklab, var(--ink-black) 78%, transparent);
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
    gap: 1rem;
    outline: none;
  }
  .head {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .desc {
    margin-bottom: 0;
    line-height: 1.5;
  }
  .desc code,
  .provider-status code {
    font-family: var(--font-pixel);
    font-size: 0.84em;
    padding: 0.05em 0.3em;
    background: color-mix(in oklab, var(--ink-bruise) 14%, transparent);
    border-radius: 2px;
  }
  .providers {
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
  }
  .provider-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 0.6rem;
  }
  .provider-card {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    text-align: left;
    padding: 0.75rem 0.8rem;
    background: color-mix(in oklab, var(--paper-bone) 92%, var(--ink-bruise));
    color: var(--ink-deep);
    border: 1px solid color-mix(in oklab, var(--ink-bruise) 40%, transparent);
    border-radius: 3px;
    text-transform: none;
    letter-spacing: 0;
  }
  .provider-card.selected {
    border-color: var(--gold-bright);
    box-shadow: inset 0 0 0 1px color-mix(in oklab, var(--gold-bright) 40%, transparent);
    background: color-mix(in oklab, var(--paper-bone) 82%, var(--gold-tarnished));
  }
  .provider-name {
    font-family: var(--font-display);
    font-size: 1rem;
  }
  .provider-status {
    font-size: 0.88rem;
    line-height: 1.4;
    color: color-mix(in oklab, var(--ink-bruise) 78%, var(--ink-black));
    display: flex;
    flex-wrap: wrap;
    gap: 0.3rem;
    align-items: center;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  .field-label {
    font-family: var(--font-pixel);
    font-size: 0.72rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--gold-tarnished);
  }
  .field input {
    width: 100%;
  }
  .error {
    margin: 0;
    padding: 0.55rem 0.7rem;
    background: color-mix(in oklab, var(--rust-blood) 16%, transparent);
    border: 1px solid color-mix(in oklab, var(--rust-blood) 55%, transparent);
    color: color-mix(in oklab, var(--rust-blood) 80%, var(--ink-black));
    border-radius: 2px;
  }
  .foot {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
    padding-top: 0.4rem;
    border-top: 1px solid color-mix(in oklab, var(--ink-bruise) 30%, transparent);
  }
</style>
