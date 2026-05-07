<!--
@component
Composer — sticky bottom input for free-text actions and slash commands.

Slash commands are documented in `lib/slash.ts`. The placeholder rotates
through suggestions so first-time users discover them organically.
Enter sends; Shift + Enter inserts a newline (mirroring Discord, Slack,
and most modern chat surfaces). Cmd / Ctrl + Enter is preserved as a
secondary submit shortcut for muscle-memory holdouts.

Slash suggestion menu: when the textarea begins with `/` and no
argument has been typed yet, a small dropdown surfaces matching
commands. Up/Down navigates, Tab/Enter completes, Esc dismisses. We
prefer Tab/Enter for completion so a fast typist can fall through the
menu without breaking flow. Shift + Enter never completes — it always
falls through to the textarea so a multi-line slash argument can be
authored without dismissing the menu first.
-->
<script lang="ts">
  import { combatFromState } from "../lib/combat";
  import {
    applyCommonAction,
    deriveCommonActions,
    type CommonAction,
  } from "../lib/common-actions";
  import { game } from "../lib/store.svelte";
  import {
    suggestSlashCommands,
    type SlashCommandDescriptor,
  } from "../lib/slash";

  let value = $state("");
  let textarea: HTMLTextAreaElement;
  // Suggestion menu state. We keep it flat (rather than a `menu: { ... }`
  // object) because the menu only has two coupled fields and Svelte 5
  // runes pick up direct field reads cheaply.
  let suggestionIndex = $state(0);
  let suggestionDismissed = $state(false);

  const suggestions = $derived<readonly SlashCommandDescriptor[]>(
    suggestionDismissed ? [] : suggestSlashCommands(value),
  );
  const showSuggestions = $derived(suggestions.length > 0 && !game.isLoading);

  // Whenever the suggestion list changes shape, clamp the selection so
  // the highlight never drifts past the visible items.
  $effect(() => {
    if (suggestionIndex >= suggestions.length) {
      suggestionIndex = 0;
    }
  });

  // When the player edits the line so the slash prefix is gone, the
  // dismiss flag becomes meaningless — re-arm it for the next slash.
  $effect(() => {
    if (!value.trimStart().startsWith("/")) {
      suggestionDismissed = false;
    }
  });

  // Auto-grow the textarea up to 6 lines so multi-paragraph actions
  // don't push the chat off-screen.
  function autoGrow(): void {
    if (!textarea) return;
    textarea.style.height = "auto";
    const next = Math.min(textarea.scrollHeight, 22 * 6);
    textarea.style.height = `${next}px`;
  }

  $effect(() => {
    void value;
    autoGrow();
  });

  async function send(): Promise<void> {
    if (!value.trim() || game.isLoading) return;
    const consumed = await game.submit(value);
    if (consumed) value = "";
  }

  function applySuggestion(cmd: SlashCommandDescriptor): void {
    // Replace just the head (everything up to the first space) with
    // the canonical command name, then add a trailing space so the
    // player can keep typing the argument body. Commands with no
    // argument body (e.g. /event, /reset, /help) are still followed
    // by a space — harmless, and keeps the rule simple.
    const head = value.trimStart();
    const spaceIdx = head.indexOf(" ");
    const tail = spaceIdx === -1 ? "" : head.slice(spaceIdx);
    value = `/${cmd.name}${tail || " "}`;
    suggestionDismissed = true;
    queueMicrotask(() => {
      textarea?.focus();
      // Place the caret after the inserted command + space so the
      // player can immediately type the argument.
      const pos = `/${cmd.name} `.length;
      textarea?.setSelectionRange(pos, pos);
    });
  }

  function onKey(event: KeyboardEvent): void {
    if (showSuggestions) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        suggestionIndex = (suggestionIndex + 1) % suggestions.length;
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        suggestionIndex =
          (suggestionIndex - 1 + suggestions.length) % suggestions.length;
        return;
      }
      // Tab always completes. Enter completes only when no modifiers
      // are held — Shift+Enter must fall through to the textarea so a
      // player can author a multi-line slash argument without first
      // dismissing the menu, and Cmd/Ctrl+Enter falls through to the
      // submit branch below.
      if (
        event.key === "Tab"
        || (event.key === "Enter"
          && !event.shiftKey
          && !event.metaKey
          && !event.ctrlKey)
      ) {
        const cmd = suggestions[suggestionIndex];
        if (cmd) {
          event.preventDefault();
          applySuggestion(cmd);
          return;
        }
      }
      if (event.key === "Escape") {
        event.preventDefault();
        suggestionDismissed = true;
        return;
      }
    }

    // Modern chat-app convention: Enter sends, Shift+Enter inserts a
    // newline. We keep Cmd/Ctrl+Enter as a secondary submit shortcut
    // for the muscle memory of users who learned the previous binding.
    //
    // `event.isComposing` guards IME input — pressing Enter to commit
    // a Japanese/Chinese composition shouldn't fire `send()`. That
    // also covers `keyCode === 229`, which some older browsers used
    // for the same condition.
    if (event.key !== "Enter") return;
    if (event.isComposing) return;
    if (event.shiftKey) return;
    event.preventDefault();
    void send();
  }

  const PLACEHOLDERS = [
    "I test the mud for fresh boot tracks.",
    "/ask Is the abbey gate watched? [likely]",
    "/event",
    "/scene I cross the bone bridge before dawn.",
    "/retreat down the chapel stair",
    "/loot the captain's chest",
    "/buy a flagon of ale and a wax-sealed map",
    "/help",
  ];
  // Pick once per mount - rotating mid-session is more annoying than helpful.
  const placeholder = PLACEHOLDERS[Math.floor(Math.random() * PLACEHOLDERS.length)]!;

  // Surface a context-sensitive hint when an encounter is active so
  // the player learns the retreat affordance without having to open
  // /help. We don't change the placeholder mid-session (placeholders
  // are sticky for muscle memory), but the footer hint can shift —
  // it's an explicit signal, not a guess at intent.
  const encounter = $derived(
    game.state === null ? null : combatFromState(game.state),
  );
  const inActiveCombat = $derived(
    encounter !== null && encounter.active,
  );

  // F-07 common-actions tray. Source of truth for which pills appear
  // is `deriveCommonActions`; this component only renders + dispatches.
  // We feed in the same combat reading the footer hint already uses
  // so tray and hint can never disagree about whether combat is live.
  const commonActions = $derived(deriveCommonActions(game.state, encounter));

  function applyTrayAction(action: CommonAction): void {
    // mousedown prevents the textarea from blurring before this fires,
    // but we still want focus + caret-set in a microtask so the
    // bound `value` write has propagated to the DOM by the time we
    // call `setSelectionRange`.
    const result = applyCommonAction(value, action);
    value = result.text;
    suggestionDismissed = false;
    queueMicrotask(() => {
      textarea?.focus();
      textarea?.setSelectionRange(result.caret, result.caret);
    });
  }
</script>

<form class="composer" onsubmit={(e) => { e.preventDefault(); void send(); }}>
  <div class="textarea-wrap">
    <textarea
      bind:this={textarea}
      bind:value
      onkeydown={onKey}
      {placeholder}
      rows="2"
      spellcheck="false"
      aria-label="Player command"
      aria-autocomplete="list"
      aria-controls={showSuggestions ? "composer-slash-menu" : undefined}
    ></textarea>

    {#if showSuggestions}
      <ul
        id="composer-slash-menu"
        class="suggestions"
        role="listbox"
        aria-label="Slash commands"
      >
        {#each suggestions as cmd, idx (cmd.name)}
          <li role="presentation">
            <button
              type="button"
              role="option"
              aria-selected={idx === suggestionIndex}
              class="suggestion"
              class:active={idx === suggestionIndex}
              onmousedown={(e) => {
                // mousedown so the textarea doesn't lose focus before we
                // re-target it inside applySuggestion's microtask.
                e.preventDefault();
                applySuggestion(cmd);
              }}
              onmouseenter={() => (suggestionIndex = idx)}
            >
              <span class="pixel name">/{cmd.name}</span>
              <span class="summary">{cmd.summary}</span>
              <span class="usage">{cmd.usage}</span>
            </button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  {#if commonActions.length > 0}
    <!--
      The tray is a horizontally-scrollable strip of pixel pills. It
      lives between the textarea and the send row so:
       * the slash suggestion menu (which floats above the textarea)
         doesn't overlap the tray, and
       * the natural left-to-right reading order is type → pick action
         (refine) → send.
      We render in document order to keep tab order intuitive; the
      buttons are real <button>s so screen readers announce labels
      and the keyboard "Enter" + "Space" semantics come for free.
    -->
    <div
      class="common-actions"
      role="toolbar"
      aria-label="Common actions"
      aria-disabled={game.isLoading ? "true" : undefined}
    >
      {#each commonActions as action (action.id)}
        <button
          type="button"
          class="action pixel"
          title={action.summary}
          aria-label={action.summary}
          disabled={game.isLoading}
          onmousedown={(e) => {
            // mousedown so the textarea doesn't blur before the
            // microtaskscheduled inside applyTrayAction re-focuses it.
            e.preventDefault();
            applyTrayAction(action);
          }}
        >
          {action.label}
        </button>
      {/each}
    </div>
  {/if}

  <div class="row">
    <span class="hint pixel">
      {#if inActiveCombat}
        Enter to send · Shift + Enter for newline · /retreat to disengage
      {:else}
        Enter to send · Shift + Enter for newline · / for commands · /help
      {/if}
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
  .textarea-wrap {
    position: relative;
  }
  textarea {
    background: color-mix(in oklab, var(--ink-deep) 80%, var(--ink-black));
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 35%, transparent);
    font-size: 1.05rem;
    min-height: 44px;
    resize: none;
    overflow-y: auto;
    width: 100%;
    box-sizing: border-box;
  }
  textarea:focus {
    border-color: var(--gold-bright);
  }

  /*
   * The suggestion menu rises *above* the textarea (anchored to its
   * bottom edge) so it doesn't push the cancel/send row off-screen on
   * short viewports, and so the visual weight of the menu lands inside
   * the chat column rather than over the player's typing.
   */
  .suggestions {
    position: absolute;
    bottom: calc(100% + 0.35rem);
    left: 0;
    right: 0;
    max-height: 14rem;
    overflow-y: auto;
    list-style: none;
    margin: 0;
    padding: 0.25rem;
    background: color-mix(in oklab, var(--ink-deep) 92%, var(--ink-black));
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 50%, transparent);
    border-radius: 2px;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.45);
    z-index: 5;
    display: grid;
    gap: 0.15rem;
  }
  .suggestion {
    display: grid;
    grid-template-columns: max-content 1fr max-content;
    align-items: baseline;
    gap: 0.6rem;
    width: 100%;
    padding: 0.4rem 0.55rem;
    background: transparent;
    border: 0;
    color: var(--paper-bone);
    text-align: left;
    cursor: pointer;
    font-size: 0.88rem;
  }
  .suggestion:hover,
  .suggestion.active {
    background: color-mix(in oklab, var(--gold-tarnished) 18%, transparent);
    color: var(--paper-warm);
  }
  .suggestion .name {
    color: var(--gold-bright);
    font-size: 0.82rem;
  }
  .suggestion .summary {
    color: var(--paper-bone);
  }
  .suggestion .usage {
    color: var(--paper-shadow);
    font-size: 0.78rem;
    font-family: var(--font-mono, ui-monospace, monospace);
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

  /*
   * F-07 common-actions tray. The tray reads as a strip of margin
   * notes pinned to the desk above the send row — small, tarnished
   * pixel pills rather than full action buttons. Horizontal scroll
   * keeps narrow viewports from forcing a wrap that would consume
   * vertical space the chat needs.
   */
  .common-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    align-items: center;
    margin-top: 0.1rem;
  }
  .common-actions[aria-disabled="true"] {
    opacity: 0.55;
  }
  .action {
    font-family: var(--font-pixel);
    font-size: 0.78rem;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    padding: 0.25rem 0.55rem;
    color: var(--paper-bone);
    background: color-mix(in oklab, var(--ink-deep) 86%, var(--ink-black));
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 35%, transparent);
    border-radius: 2px;
    cursor: pointer;
    line-height: 1.2;
    /*
     * Subtle inset shadow so the pill reads as carved into the
     * composer surface rather than floating above it. Matches the
     * receipt-strip + chaos-pip vocabulary already on screen.
     */
    box-shadow: inset 0 -1px 0
      color-mix(in oklab, var(--gold-tarnished) 25%, transparent);
  }
  .action:hover:not(:disabled),
  .action:focus-visible {
    color: var(--gold-bright);
    border-color: var(--gold-bright);
    background: color-mix(in oklab, var(--gold-tarnished) 10%, var(--ink-deep));
    outline: none;
  }
  .action:disabled {
    cursor: not-allowed;
    color: var(--paper-shadow);
  }
</style>
