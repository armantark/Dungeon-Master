<!--
@component
NPCsPanel — recurring figures the player has actually met.

NPCs are mutated dynamically by the backend turn pipeline (F-04): each
resolved turn can run a structured `NPCUpdater` pass that creates,
updates, or retires NPCs and reports the touched ids on the latest
oracle outcome. We surface that two ways, mirroring the threads panel:

  1. Sort: active NPCs sit above retired ones, and within each status
     group recently-touched cards float to the top so the player's eye
     lands on whoever just changed.
  2. Pulse + pip: a one-shot CSS animation on freshly-touched cards
     plus a small caption ("advanced" / "newly retired") so the change
     is legible even after the pulse fades. Reduced-motion users get
     the static accent only.

Retired NPCs stay in canon (they're not deleted) so the panel always
matches what the backend persists; we just mute them so the active
cast keeps visual priority.

F-16 contract: this panel renders only **introduced** NPCs — anyone
the committed narration has actually presented to the player. The
backend may also track a hidden cast (foreshadowed antagonists,
pre-authored campaign continuity) on `state.hidden_npcs`, but those
are deliberately not visible here. Surfacing them by name before
the player has met them was the spoiler bug F-16 fixed; the
backend's post-narration reveal step moves a hidden NPC into
`state.npcs` once committed prose names them, at which point this
panel will pick them up via the normal `recentlyTouchedIds` flow.

Read-only on purpose — F-04 made NPCs canon-driven, not user-edited.
-->
<script lang="ts">
  import { onDestroy, tick } from "svelte";
  import {
    npcDisplayLabel,
    npcKnownByDescriptor,
    sortNpcsForDisplay,
  } from "../lib/npcs";
  import type { NPC } from "../lib/types";

  type Props = {
    npcs: readonly NPC[];
    /**
     * Set of NPC ids the latest turn touched. Optional so legacy
     * callers (e.g. tests, future read-only embeds) keep working.
     * The Inspector derives this from `recentlyTouchedNpcIds`.
     */
    recentlyTouchedIds?: ReadonlySet<string>;
    focusedId?: string | null;
    focusSeq?: number;
  };
  const {
    npcs,
    recentlyTouchedIds = new Set<string>(),
    focusedId = null,
    focusSeq = 0,
  }: Props = $props();

  const ordered = $derived(sortNpcsForDisplay(npcs, recentlyTouchedIds));

  let listEl: HTMLUListElement | undefined = $state();
  let flashingId: string | null = $state(null);
  let lastFocusSeq: number = $state(-1);
  let focusTimer: ReturnType<typeof setTimeout> | null = null;

  async function revealFocusedNpc(npcId: string): Promise<void> {
    await tick();
    const target = listEl?.querySelector<HTMLElement>(
      `[data-npc-id="${CSS.escape(npcId)}"]`,
    );
    if (target === undefined || target === null) return;
    target.scrollIntoView({ behavior: "smooth", block: "nearest" });
    flashingId = npcId;
    if (focusTimer !== null) clearTimeout(focusTimer);
    focusTimer = setTimeout(() => {
      flashingId = null;
      focusTimer = null;
    }, 1700);
  }

  $effect(() => {
    if (focusedId === null) return;
    if (focusSeq === lastFocusSeq) return;
    lastFocusSeq = focusSeq;
    void revealFocusedNpc(focusedId);
  });

  onDestroy(() => {
    if (focusTimer !== null) clearTimeout(focusTimer);
  });
</script>

{#if npcs.length === 0}
  <!--
    F-16: with the introduced-only contract, an empty roster is
    not "the world is empty" — it's "you haven't materially
    encountered anyone yet, but the campaign may still have
    figures waiting in the wings." The copy makes that clearer
    than the previous "No NPCs in scene." which read as a
    factual claim about the world.
  -->
  <p class="muted">No known recurring figures yet.</p>
{:else}
  <ul bind:this={listEl}>
    {#each ordered as npc (npc.id)}
      {@const justTouched = recentlyTouchedIds.has(npc.id)}
      {@const isRetired = npc.status === "retired"}
      {@const knownByDescriptor = npcKnownByDescriptor(npc)}
      <li
        data-npc-id={npc.id}
        class:retired={isRetired}
        class:advanced={justTouched}
        class:focused={flashingId === npc.id}
      >
        <div class="row">
          <h4 class:descriptor={knownByDescriptor}>{npcDisplayLabel(npc)}</h4>
          {#if knownByDescriptor}
            <span
              class="status mono descriptor-pip"
              title="The player knows this recurring figure by sign, not by a granted proper name."
            >
              known by sign
            </span>
          {/if}
          {#if isRetired}
            <span class="status mono" data-status="retired">retired</span>
          {/if}
          {#if justTouched}
            <span
              class="status mono advanced-pip"
              title="This NPC changed on the latest turn."
            >
              {isRetired ? "newly retired" : "advanced"}
            </span>
          {/if}
        </div>
        <p class="meta">
          <span class="mono small">{npc.role}</span>
        </p>
        {#if npc.disposition.trim() !== ""}
          <!--
            B-01: the disposition used to share a flex row with the
            role chip and was clamped to two lines so the row
            wouldn't tower over the role pill. That hid the back of
            most dispositions even though the panel itself can
            scroll. We now give it its own paragraph below so it can
            wrap freely; the `title` attribute is preserved for
            keyboard / assistive-tech users who relied on it.
          -->
          <p class="disposition muted" title={npc.disposition}>{npc.disposition}</p>
        {/if}
      </li>
    {/each}
  </ul>
{/if}

<style>
  ul {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  li {
    border-left: 2px solid color-mix(in oklab, var(--gold-tarnished) 60%, transparent);
    padding: 0.32rem 0.6rem;
    background: rgba(0, 0, 0, 0.18);
    /*
     * `position: relative` so the one-shot advanced pulse can paint a
     * faint ring via box-shadow without being clipped by the panel's
     * scroll container. Same trick as ThreadsPanel.
     */
    position: relative;
  }
  /*
   * Retired NPCs stay in canon (the backend persists them with
   * status="retired" rather than deleting), so the panel keeps showing
   * them — but muted, with a verdigris rail to match the resolved-thread
   * visual language. Both are "off the active board" without being
   * gone.
   */
  li.retired {
    opacity: 0.55;
    border-left-color: color-mix(in oklab, var(--green-verdigris) 70%, transparent);
  }
  /*
   * "Advanced" is the visual companion to `recentlyTouchedIds`. We
   * brighten the left rail to gold (the engine voice) and play a
   * single short pulse so the card calls attention to itself exactly
   * once when it lands. Pulse is gated by prefers-reduced-motion; the
   * static gold rail still carries the recency cue when motion is
   * muted.
   *
   * We deliberately don't pulse already-retired cards — the static
   * gold rail + "newly retired" pip is enough, and a pulse on a muted
   * card reads as visual noise rather than a signal.
   */
  li.advanced {
    border-left-color: var(--gold-bright);
  }
  li.advanced:not(.retired) {
    animation: npc-pulse 1.6s ease-out 1;
  }
  li.focused {
    box-shadow:
      0 0 0 1px color-mix(in oklab, var(--gold-bright) 55%, transparent) inset,
      0 0 0 6px color-mix(in oklab, var(--gold-bright) 16%, transparent);
  }
  @keyframes npc-pulse {
    0% {
      box-shadow: 0 0 0 0 color-mix(in oklab, var(--gold-bright) 55%, transparent);
    }
    100% {
      box-shadow: 0 0 0 6px color-mix(in oklab, var(--gold-bright) 0%, transparent);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    li.advanced:not(.retired) {
      animation: none;
    }
  }
  .row {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    flex-wrap: wrap;
  }
  h4 {
    font-family: var(--font-display);
    font-size: 0.96rem;
    margin: 0;
    color: var(--paper-warm);
  }
  h4.descriptor {
    font-style: italic;
  }
  .status {
    font-size: 0.65rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--rust-iron);
  }
  .status[data-status="retired"] {
    color: var(--green-verdigris);
  }
  .advanced-pip {
    color: var(--gold-bright);
  }
  .descriptor-pip {
    color: color-mix(in oklab, var(--gold-bright) 72%, var(--paper-bone));
  }
  .meta {
    margin: 0.15rem 0 0;
    font-size: 0.82rem;
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }
  /*
   * B-01: the disposition lives on its own line below the role chip
   * so it can wrap freely without making the role line tower over
   * the rest of the row. We keep it visually muted (the global
   * `.muted` rule supplies the color) but add explicit prose
   * styling here because the global muted is otherwise font-size
   * agnostic, and we want this prose to read at the same density as
   * a thread's stakes paragraph.
   */
  .disposition {
    margin: 0.2rem 0 0;
    font-size: 0.82rem;
    line-height: 1.35;
    overflow-wrap: anywhere;
  }
  .small {
    font-size: 0.72rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--gold-tarnished);
  }
</style>
