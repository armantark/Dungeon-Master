<!--
@component
CharacterFolio — persistent left rail for who you are and what you carry.

This sits beside the chat because identity + inventory are not "deep
inspector" data. They are the immediate play affordances the player
checks before declaring an action.
-->
<script lang="ts">
  import type { CharacterSheet, GameState, InventoryItem } from "../lib/types";

  type Props = { state: GameState };
  const { state: gs }: Props = $props();

  const character = $derived.by<CharacterSheet>(() => {
    return gs.character ?? {
      name: "Unnamed wanderer",
      archetype: "Unknown wanderer",
      epithet: gs.player_notes,
      backstory: gs.player_notes,
      drive: "Survive the next turning of the wheel.",
      flaw: "Too much remains undefined.",
      condition: "Unrecorded.",
      inventory: [],
    };
  });

  const inventory = $derived.by<InventoryItem[]>(() => {
    if (character.inventory.length > 0) return character.inventory;
    return [
      {
        id: "empty",
        name: "No tracked gear",
        details: "Inventory has not been established for this campaign yet.",
      },
    ];
  });
</script>

<aside class="folio iron" aria-label="Character sheet and inventory">
  <div class="plate">
    <span class="kicker">{character.archetype}</span>
    <h2>{character.name}</h2>
    <p class="epithet">{character.epithet || character.backstory || gs.player_notes}</p>
  </div>

  <section class="condition">
    <span class="kicker">Condition</span>
    <p>{character.condition}</p>
    <span class="kicker kicker--sub">Drive</span>
    <p class="drive">{character.drive}</p>
  </section>

  <section class="inventory">
    <span class="kicker">Inventory</span>
    <ul>
      {#each inventory as item (item.id)}
        <li>
          <strong>{item.name}</strong>
          {#if item.details}
            <span>{item.details}</span>
          {/if}
        </li>
      {/each}
    </ul>
  </section>
</aside>

<style>
  .folio {
    align-self: start;
    position: sticky;
    top: 1rem;
    height: calc(100vh - 7.2rem);
    min-height: 0;
    overflow: hidden;
    display: grid;
    grid-template-rows: auto auto minmax(0, 1fr);
    border: var(--rule-hair);
    box-shadow: var(--shadow-deep), var(--shadow-leather);
  }
  .plate,
  .condition,
  .inventory {
    padding: 0.7rem 0.8rem;
    border-bottom: var(--rule-hair);
  }
  .plate h2 {
    font-size: 1.18rem;
    line-height: 1.05;
    margin: 0.15rem 0 0.25rem;
  }
  .epithet,
  .condition p {
    margin: 0;
    color: var(--paper-bone);
    font-size: 0.86rem;
    line-height: 1.34;
  }
  .drive {
    margin-top: 0.14rem;
  }
  .kicker--sub {
    margin-top: 0.55rem;
  }
  .epithet {
    display: -webkit-box;
    line-clamp: 4;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .condition p {
    display: -webkit-box;
    line-clamp: 1;
    -webkit-line-clamp: 1;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .inventory {
    min-height: 0;
    overflow: hidden;
    border-bottom: 0;
    display: flex;
    flex-direction: column;
  }
  .inventory ul {
    list-style: none;
    padding: 0;
    margin: 0.35rem 0 0;
    overflow-y: auto;
    min-height: 0;
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
  }
  .inventory li {
    border-left: 2px solid color-mix(in oklab, var(--gold-tarnished) 65%, transparent);
    background: rgba(0, 0, 0, 0.22);
    padding: 0.45rem 0.6rem;
  }
  .inventory strong {
    display: block;
    font-family: var(--font-display);
    font-size: 0.98rem;
    color: var(--paper-warm);
    font-weight: 400;
    line-height: 1.05;
  }
  .inventory span {
    display: block;
    margin-top: 0.18rem;
    color: var(--paper-shadow);
    font-size: 0.82rem;
    line-height: 1.32;
  }
</style>
