<!--
@component
NotesEditor — edit setting + player notes.
-->
<script lang="ts">
  import { untrack } from "svelte";
  import { game } from "../lib/store.svelte";
  import type { GameState } from "../lib/types";

  type Props = { state: GameState };
  // We rebind the `state` prop to `gs` because Svelte interprets a local
  // identifier called `state` as a store subscription target when the
  // `$state` rune is also used in the file.
  const { state: gs }: Props = $props();

  // Seed the edit buffers from the canonical state without subscribing to
  // it (the $effect below handles re-syncing on reset). `untrack` here
  // documents that the initial read is one-shot.
  let setting = $state(untrack(() => gs.setting_notes));
  let player = $state(untrack(() => gs.player_notes));
  let editing = $state(false);

  // When the canonical state changes (e.g. after a reset), pull the new
  // values into our editing buffers so we don't show stale text.
  $effect(() => {
    setting = gs.setting_notes;
    player = gs.player_notes;
  });

  const dirty = $derived(
    setting !== gs.setting_notes || player !== gs.player_notes,
  );

  async function commit(): Promise<void> {
    if (!dirty || game.isLoading) return;
    await game.updateNotes(setting, player);
    editing = false;
  }

  function revert(): void {
    setting = gs.setting_notes;
    player = gs.player_notes;
    editing = false;
  }
</script>

<div class="notes">
  {#if editing}
    <label for="setting">Setting</label>
    <textarea id="setting" bind:value={setting} rows="3"></textarea>

    <label for="player">Player</label>
    <textarea id="player" bind:value={player} rows="2"></textarea>

    <div class="row">
      <button class="ghost" onclick={revert} disabled={game.isLoading}>Cancel</button>
      <button onclick={commit} disabled={!dirty || game.isLoading}>Save notes</button>
    </div>
  {:else}
    <div class="preview">
      <div>
        <span class="kicker">Setting</span>
        <p>{gs.setting_notes}</p>
      </div>
      <div>
        <span class="kicker">Player</span>
        <p>{gs.player_notes}</p>
      </div>
    </div>
    <div class="row">
      <button class="ghost" onclick={() => (editing = true)}>Edit notes</button>
    </div>
  {/if}
</div>

<style>
  .notes {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  textarea {
    min-height: 42px;
    max-height: 82px;
    font-size: 0.92rem;
    line-height: 1.32;
  }
  .preview {
    display: grid;
    gap: 0.55rem;
  }
  .preview p {
    margin: 0.12rem 0 0;
    font-size: 0.9rem;
    line-height: 1.36;
    display: -webkit-box;
    line-clamp: 4;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  label {
    margin-bottom: 0;
  }
  .row {
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
  }
</style>
