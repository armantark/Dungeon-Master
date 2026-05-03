<!--
@component
Composer — sticky bottom input for free-text actions and slash commands.

Slash commands are documented in `lib/slash.ts`. The placeholder rotates
through suggestions so first-time users discover them organically.
Cmd / Ctrl + Enter sends; bare Enter inserts a newline (mirroring chat
tools the user already has muscle memory for).
-->
<script lang="ts">
  import { game } from "../lib/store.svelte";

  let value = $state("");
  let textarea: HTMLTextAreaElement;

  // Auto-grow the textarea up to 6 lines so multi-paragraph actions
  // don't push the chat off-screen.
  function autoGrow(): void {
    if (!textarea) return;
    textarea.style.height = "auto";
    const next = Math.min(textarea.scrollHeight, 22 * 6);
    textarea.style.height = `${next}px`;
  }

  $effect(() => {
    // Re-run on every value change.
    void value;
    autoGrow();
  });

  async function send(): Promise<void> {
    if (!value.trim() || game.isLoading) return;
    const consumed = await game.submit(value);
    if (consumed) value = "";
  }

  function onKey(event: KeyboardEvent): void {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      void send();
    }
  }

  const PLACEHOLDERS = [
    "I test the mud for fresh boot tracks.",
    "/ask Is the abbey gate watched? [likely]",
    "/event",
    "/scene I cross the bone bridge before dawn.",
    "/help",
  ];
  // Pick once per mount - rotating mid-session is more annoying than helpful.
  const placeholder = PLACEHOLDERS[Math.floor(Math.random() * PLACEHOLDERS.length)]!;
</script>

<form class="composer" onsubmit={(e) => { e.preventDefault(); void send(); }}>
  <textarea
    bind:this={textarea}
    bind:value
    onkeydown={onKey}
    {placeholder}
    rows="2"
    spellcheck="false"
    aria-label="Player command"
  ></textarea>

  <div class="row">
    <span class="hint pixel">
      Cmd/Ctrl + Enter to send · /help for commands
    </span>
    <div class="actions">
      {#if game.isLoading && game.cancelLabel}
        <button class="ghost" type="button" onclick={() => game.cancelCurrentRequest()}>
          {game.cancelLabel}
        </button>
      {/if}
      <button type="submit" disabled={game.isLoading || !value.trim()}>
        Send
      </button>
    </div>
  </div>
</form>

<style>
  .composer {
    background: var(--ink-deep);
    border-top: var(--rule-hair);
    padding: 0.7rem 1rem 0.9rem;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  textarea {
    background: color-mix(in oklab, var(--ink-deep) 80%, var(--ink-black));
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 35%, transparent);
    font-size: 1.05rem;
    min-height: 44px;
    resize: none;
    overflow-y: auto;
  }
  textarea:focus {
    border-color: var(--gold-bright);
  }
  .row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
  }
  .actions {
    display: flex;
    gap: 0.5rem;
    align-items: center;
  }
  .hint {
    color: var(--paper-shadow);
    font-size: 0.78rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
</style>
