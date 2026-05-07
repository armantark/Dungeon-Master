<!--
@component
DirectivesEditor — persistent OOC steering for the campaign (B-02).

This replaces the old "Notes" editor, which was conceptually muddled:
that surface tried to be both canonical campaign material (world
bible, character backstory) and a freeform scratchpad. The user
correctly observed that a vague "Edit notes" button reads like a
demand for journaling when the only durable use-case is stable
prompt steering — for example "the hierophant cannot speak first" or
"keep miracles subtle."

Directives therefore have a sharper contract:
  - They live on `state.directives` (separate from `setting_notes` /
    `player_notes`), and the backend never appends them to the
    action log. They are OOC, not transcript canon.
  - They feed every model-touching prompt (narrator, Cairn engine,
    NPC updater, OOC explainer) so a single edit propagates without
    the player retyping it every turn.
  - The Inspector is the only edit surface. There are no slash
    commands; directives are deliberately a low-frequency, high-care
    setting, not chat input.

The editor is closed/idle by default. We render the current values
inline in a quiet read-mode so the player sees what the system is
already steering on, plus a single "Edit directives" affordance.
Editing reveals two labeled textareas with explicit copy clarifying
the surface's meaning. Save commits; Cancel reverts to the canonical
buffer without round-tripping the backend.
-->
<script lang="ts">
  import { untrack } from "svelte";
  import { game } from "../lib/store.svelte";
  import type { GameState } from "../lib/types";

  type Props = {
    state: GameState;
    /**
     * When true, the editor renders read-only archive prose instead
     * of the edit affordance. The Inspector passes
     * `archived = campaign_status === 'ended'` here so terminal
     * campaigns still show their historical directives but no
     * longer let the player mutate them — the backend would
     * reject the call with a 409 anyway, surfacing a useless
     * error toast.
     */
    archived?: boolean;
  };
  // Rebound to `gs` to avoid colliding with Svelte 5's `$state` rune
  // when this file uses both the rune and the prop name.
  const { state: gs, archived = false }: Props = $props();

  // Edit buffers seeded from the canonical state on first mount.
  // `untrack` documents that the initial seed is one-shot — we
  // resync below in `$effect` only when the canonical values
  // actually change (e.g. after a save commit or save-slot swap).
  let world = $state(untrack(() => gs.directives.world_guidance));
  let play = $state(untrack(() => gs.directives.play_guidance));
  let editing = $state(false);

  // Resync buffers when canonical state replaces them out from under
  // us. This covers two cases:
  //   1. Successful commit: backend echoes the new directives, our
  //      buffers must match so `dirty` flips back to false.
  //   2. Save-slot switch: the store rebinds `state` wholesale, and
  //      stale buffers from the previous campaign would otherwise
  //      ghost into the new one's editor.
  $effect(() => {
    world = gs.directives.world_guidance;
    play = gs.directives.play_guidance;
  });

  const dirty = $derived(
    world !== gs.directives.world_guidance ||
      play !== gs.directives.play_guidance,
  );
  const hasContent = $derived(
    gs.directives.world_guidance.trim() !== "" ||
      gs.directives.play_guidance.trim() !== "",
  );

  async function commit(): Promise<void> {
    if (!dirty || game.isLoading) return;
    await game.updateDirectives(world, play);
    editing = false;
  }

  function revert(): void {
    world = gs.directives.world_guidance;
    play = gs.directives.play_guidance;
    editing = false;
  }
</script>

<div class="directives">
  <p class="kicker">Out-of-character · persistent</p>
  <p class="muted intro">
    Durable steering the system remembers across turns. Not narrated,
    not part of the story log — closer to a stable system-prompt
    nudge than a journal. Empty fields are fine; only fill these in
    if the model has been quietly missing a rule you don't want to
    keep retyping.
  </p>

  {#if archived}
    <!--
      Mirror the old archive contract: render the canonical
      directives as static prose so the player can read what the
      campaign was steered on, but never offer an edit
      affordance. A disabled textarea would imply "you could edit
      this if X" and invite the question; static prose says
      "this is preserved as canon" without ambiguity.
    -->
    {#if hasContent}
      {#if gs.directives.world_guidance.trim() !== ""}
        <section>
          <span class="kicker">World</span>
          <p class="prose">{gs.directives.world_guidance}</p>
        </section>
      {/if}
      {#if gs.directives.play_guidance.trim() !== ""}
        <section>
          <span class="kicker">Play</span>
          <p class="prose">{gs.directives.play_guidance}</p>
        </section>
      {/if}
    {:else}
      <p class="muted archived-hint">
        Archived — no directives were set on this campaign.
      </p>
    {/if}
  {:else if editing}
    <label for="directives-world">World guidance</label>
    <p class="muted hint">
      Stable rules of this world the model should respect. Examples:
      “miracles are subtle,” “coin is rare,” “the hierophant cannot
      speak first.”
    </p>
    <textarea
      id="directives-world"
      bind:value={world}
      rows="3"
      placeholder="No world guidance set."
    ></textarea>

    <label for="directives-play">Play guidance</label>
    <p class="muted hint">
      How the system should pace and frame play for you. Examples:
      “end scenes on a question, not a cliffhanger,” “keep combat
      lethal,” “let me sit with silences.”
    </p>
    <textarea
      id="directives-play"
      bind:value={play}
      rows="3"
      placeholder="No play guidance set."
    ></textarea>

    <div class="row">
      <button class="ghost" onclick={revert} disabled={game.isLoading}>
        Cancel
      </button>
      <button onclick={commit} disabled={!dirty || game.isLoading}>
        Save directives
      </button>
    </div>
  {:else}
    <div class="preview">
      {#if hasContent}
        {#if gs.directives.world_guidance.trim() !== ""}
          <section>
            <span class="kicker">World</span>
            <p class="prose">{gs.directives.world_guidance}</p>
          </section>
        {/if}
        {#if gs.directives.play_guidance.trim() !== ""}
          <section>
            <span class="kicker">Play</span>
            <p class="prose">{gs.directives.play_guidance}</p>
          </section>
        {/if}
      {:else}
        <p class="muted empty">
          No directives set. The campaign runs on its own canon
          alone.
        </p>
      {/if}
    </div>
    <div class="row">
      <button class="ghost" onclick={() => (editing = true)}>
        {hasContent ? "Edit directives" : "Add directives"}
      </button>
    </div>
  {/if}
</div>

<style>
  .directives {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  /*
   * The intro copy is the load-bearing piece of B-02 — it replaces
   * the missing affordance copy of the old "Edit notes" surface.
   * Keep it tight (one short paragraph) so the drawer stays
   * peek-on-demand; longer prose would feel like a settings tutorial.
   */
  .intro {
    margin: 0;
    font-size: 0.82rem;
    line-height: 1.4;
  }
  .hint {
    margin: 0.1rem 0 0.3rem;
    font-size: 0.78rem;
    line-height: 1.35;
  }
  textarea {
    /*
     * Mirrored from the previous notes editor: short by default so
     * the drawer doesn't tower, but tall enough to show 2-3 lines
     * without scrolling within the textarea itself. The drawer body
     * absorbs additional height growth via its own scroll gutter.
     */
    min-height: 48px;
    max-height: 110px;
    font-size: 0.92rem;
    line-height: 1.32;
  }
  label {
    margin-bottom: 0;
    font-size: 0.78rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--gold-tarnished);
  }
  section {
    /*
     * Two-line section: kicker pip on top, prose flush below.
     * Matches the read-mode shape of the (former) notes editor so
     * the visual rhythm of the inspector doesn't shift just
     * because the surface was renamed.
     */
    display: grid;
    gap: 0.12rem;
  }
  .preview {
    display: grid;
    gap: 0.55rem;
  }
  .prose {
    margin: 0;
    font-size: 0.9rem;
    line-height: 1.36;
    /*
     * Same prose pattern as the old notes preview: preserve
     * intentional paragraph breaks and let long unbreakable tokens
     * (player-written URLs, model names) wrap rather than bleed.
     */
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
  .empty,
  .archived-hint {
    margin: 0;
    font-size: 0.85rem;
    line-height: 1.36;
  }
  .row {
    display: flex;
    gap: 0.5rem;
    justify-content: flex-end;
  }
</style>
