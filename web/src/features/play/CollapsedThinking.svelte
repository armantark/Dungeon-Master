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
  import type { Snippet } from "svelte";
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
    // Optional snippet rendered at the top of the expanded body, before
    // the trace text. Used by `ChatMessage` to show a compact stage
    // checklist that lets the player audit the pipeline that produced
    // this turn — kept as a snippet (rather than a hardcoded prop)
    // so the trace block stays agnostic to whatever audit content the
    // caller wants to surface.
    headerSnippet?: Snippet;
    // Optional always-visible summary rendered in the strip itself
    // (next to the dot/label, before the chevron). Used to surface
    // the total roundtrip time of the underlying turn so the player
    // can see it without having to expand the trace. Falsy → omitted.
    summary?: string | null;
    // Force the block to render even when text is empty and no trace
    // exists. Used when only the headerSnippet/summary carry useful
    // content — without this we'd hide the strip just because the
    // model produced no reasoning, even if the timings are present.
    forceVisible?: boolean;
  };
  const {
    text,
    streaming = false,
    hideWhenEmpty = true,
    headerSnippet,
    summary = null,
    forceVisible = false,
  }: Props = $props();

  // `untrack` so a default `false` here doesn't pin the component into a
  // re-render loop on every text delta — `open` stays a pure local toggle.
  let open: boolean = $state(untrack(() => false));

  const hasText = $derived(text.trim() !== "");
  const visible = $derived(
    streaming || hasText || !hideWhenEmpty || forceVisible,
  );
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
        {#if streaming}Thinking…{:else if hasText}Reasoning trace{:else}Pipeline trace{/if}
      </span>
      {#if summary}
        <span class="summary">{summary}</span>
      {/if}
      {#if !streaming && wordCount > 0}
        <span class="meta">{wordCount} {wordCount === 1 ? "word" : "words"}</span>
      {:else if streaming && lineCount > 0}
        <span class="meta">{lineCount} {lineCount === 1 ? "line" : "lines"}</span>
      {/if}
      <span class="chev" aria-hidden="true">{open ? "▾" : "▸"}</span>
    </button>

    {#if open}
      <div class="body">
        {#if headerSnippet}
          <div class="header-block">
            {@render headerSnippet()}
          </div>
        {/if}
        {#if hasText || streaming}
          <pre class="trace">{text || (streaming ? "…" : "")}</pre>
        {/if}
      </div>
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
    display: flex;
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
  .label {
    flex: 1 1 auto;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }
  .summary {
    flex: 0 0 auto;
    color: var(--gold-tarnished);
    font-size: 0.7rem;
    letter-spacing: 0.04em;
    font-variant-numeric: tabular-nums;
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
    border-top: 1px dashed color-mix(in oklab, var(--paper-shadow) 35%, transparent);
    background: color-mix(in oklab, var(--ink-black) 50%, transparent);
    max-height: 16rem;
    overflow-y: auto;
  }
  .header-block {
    /* Holds the optional caller-provided summary (e.g. compact stage
     * checklist). Padded to match `.trace` so the two read as
     * vertically continuous; no top border because the dashed strip
     * border already separates the body from the strip. */
    padding: 0.55rem 0.75rem 0.4rem;
  }
  .trace {
    margin: 0;
    padding: 0.4rem 0.75rem 0.7rem;
    /* Trace text uses the pixel face because this is engine-voice
     * content; the narrative voice should never bleed into the trace
     * block. Wrap and scroll behavior live on `.body` so the header
     * block and the trace share the same scrollable surface. */
    font-family: var(--font-pixel);
    font-size: 0.78rem;
    line-height: 1.45;
    color: color-mix(in oklab, var(--paper-bone) 75%, transparent);
    white-space: pre-wrap;
    word-wrap: break-word;
    -webkit-font-smoothing: none;
  }
</style>
