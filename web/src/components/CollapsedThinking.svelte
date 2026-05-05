<!--
@component
CollapsedThinking — the model's reasoning trace, collapsed by default.

Why this exists: modern chat surfaces (Claude, ChatGPT, Cursor) all show
"the model is thinking" as a subdued, collapsible block above the answer.
Without that, a long latency before the first content token reads as a
freeze. With it, the player has something to glance at — and they can
ignore it entirely if they want the fiction unbroken.

Visual hierarchy: the thinking block must be *subordinate* to the
narrative. We keep it in the engine voice (Alagard pixel) so it reads
as machinery, not story. The narrative voice (Cormorant) is reserved
for the actual DM bubble below. This separation is the same three-voice
rule the rest of the UI already follows: engine speaks pixel, DM speaks
serif, scene heads speak the display SC face.

Two states:
  - streaming   the trace is growing. Default-collapsed; players who
                want to read along can expand. We show a small pulse
                glyph so the player knows *something* is happening.
  - persisted   the trace is final. Still default-collapsed because the
                whole point is that the answer is the headline; the
                reasoning is verifiable evidence on demand, not a
                second body paragraph.

The component never mutates state — it's a pure renderer over the text
prop and an internal `open` toggle. Keeping it stateless against the
model output means refresh/regenerate flows that hand it new text just
work without any reset choreography.
-->
<script lang="ts">
  import { untrack } from "svelte";

  type Props = {
    text: string;
    streaming?: boolean;
    // When true, the block is hidden when text is empty. Persisted
    // thinking on a historical message renders nothing if the model
    // produced no trace; live streaming should still show the block
    // while the trace catches up, so the call site sets this false
    // for the streaming case.
    hideWhenEmpty?: boolean;
  };
  const { text, streaming = false, hideWhenEmpty = true }: Props = $props();

  // `untrack` so a default `false` here doesn't pin the component into a
  // re-render loop on every text delta — `open` stays a pure local toggle.
  let open: boolean = $state(untrack(() => false));

  const visible = $derived(streaming || text.trim() !== "" || !hideWhenEmpty);
  const lineCount = $derived(text === "" ? 0 : text.split("\n").length);
  const wordCount = $derived(text === "" ? 0 : text.trim().split(/\s+/).length);
</script>

{#if visible}
  <div class="thinking" class:open class:streaming>
    <button
      type="button"
      class="strip pixel"
      onclick={() => (open = !open)}
      aria-expanded={open}
    >
      <span class="dot" aria-hidden="true"></span>
      <span class="label">
        {#if streaming}Thinking…{:else}Reasoning trace{/if}
      </span>
      {#if !streaming && wordCount > 0}
        <span class="meta">{wordCount} {wordCount === 1 ? "word" : "words"}</span>
      {:else if streaming && lineCount > 0}
        <span class="meta">{lineCount} {lineCount === 1 ? "line" : "lines"}</span>
      {/if}
      <span class="chev" aria-hidden="true">{open ? "▾" : "▸"}</span>
    </button>

    {#if open}
      <pre class="body">{text || (streaming ? "…" : "")}</pre>
    {/if}
  </div>
{/if}

<style>
  .thinking {
    /* Subdued container — a hair-rule and a tinted background so it
     * reads as machinery alongside the prose without competing with
     * the receipt strip below. */
    border-left: 2px solid color-mix(in oklab, var(--paper-shadow) 55%, transparent);
    margin: 0.25rem 0 0.4rem;
    background: color-mix(in oklab, var(--ink-deep) 60%, transparent);
  }
  .strip {
    display: grid;
    grid-template-columns: auto 1fr auto auto;
    align-items: center;
    gap: 0.55rem;
    width: 100%;
    padding: 0.32rem 0.6rem;
    color: var(--paper-shadow);
    background: transparent;
    border: 0;
    text-align: left;
    text-transform: none;
    letter-spacing: 0;
    cursor: pointer;
    font-size: 0.78rem;
  }
  .strip:hover {
    color: var(--paper-bone);
  }
  .label {
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .meta {
    color: color-mix(in oklab, var(--paper-shadow) 70%, transparent);
    font-size: 0.7rem;
  }
  .chev {
    color: var(--paper-shadow);
  }

  /* The dot is a single pixel-square that pulses while streaming and
   * stays muted once the trace is final. We deliberately don't reuse
   * the LoadingPanel three-dot lamp here because that one is a
   * "working" surface; a pulsing single dot reads as a status light. */
  .dot {
    width: 0.45rem;
    height: 0.45rem;
    background: var(--paper-shadow);
    box-shadow: 0 0 0 1px color-mix(in oklab, var(--paper-shadow) 40%, transparent);
  }
  .thinking.streaming .dot {
    background: var(--gold-candle);
    box-shadow: 0 0 6px color-mix(in oklab, var(--gold-bright) 60%, transparent);
    animation: pulse 1.2s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { opacity: 0.45; transform: scale(0.85); }
    50% { opacity: 1; transform: scale(1.05); }
  }
  @media (prefers-reduced-motion: reduce) {
    .thinking.streaming .dot {
      animation: none;
      opacity: 0.85;
    }
  }

  .body {
    margin: 0;
    padding: 0.55rem 0.75rem 0.7rem;
    /* Body uses the pixel face because this is engine-voice text; the
     * narrative voice should never bleed into the trace block. We cap
     * height and scroll because long traces shouldn't push the prose
     * off-screen — the trace is supposed to be subordinate. */
    font-family: var(--font-pixel);
    font-size: 0.78rem;
    line-height: 1.45;
    color: color-mix(in oklab, var(--paper-bone) 75%, transparent);
    white-space: pre-wrap;
    word-wrap: break-word;
    max-height: 16rem;
    overflow-y: auto;
    border-top: 1px dashed color-mix(in oklab, var(--paper-shadow) 35%, transparent);
    background: color-mix(in oklab, var(--ink-black) 50%, transparent);
    -webkit-font-smoothing: none;
  }
</style>
