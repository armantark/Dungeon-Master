<script lang="ts">
  import type { CharacterSheet } from "../lib/types";

  type Props = {
    template: CharacterSheet;
    onEdit: (template: CharacterSheet) => void;
    onQuickstart: (template: CharacterSheet) => void;
  };

  const { template, onEdit, onQuickstart }: Props = $props();
</script>

<article class="card iron">
  <div class="kicker">{template.archetype}</div>
  <h3>{template.name}</h3>
  <p class="epithet">{template.epithet}</p>
  <p class="body">{template.backstory}</p>
  <div class="meta">
    <div>
      <span class="kicker">Drive</span>
      <p>{template.drive}</p>
    </div>
    <div>
      <span class="kicker">Flaw</span>
      <p>{template.flaw}</p>
    </div>
  </div>
  <div class="actions">
    <button class="ghost" onclick={() => onEdit(template)}>Edit</button>
    <button onclick={() => onQuickstart(template)}>Quickstart</button>
  </div>
</article>

<style>
  .card {
    padding: 1rem;
    display: grid;
    gap: 0.45rem;
    border: var(--rule-hair);
  }
  h3 {
    font-size: 1.2rem;
    margin: 0;
  }
  .epithet,
  .body,
  .meta p {
    margin: 0;
    color: var(--paper-bone);
  }
  .body {
    font-size: 0.95rem;
    line-height: 1.42;
  }
  .meta {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.8rem;
    padding-top: 0.2rem;
  }
  .meta p {
    font-size: 0.84rem;
    line-height: 1.3;
  }
  .actions {
    display: flex;
    gap: 0.6rem;
    justify-content: flex-end;
  }
</style>
