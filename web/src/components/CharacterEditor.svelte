<script lang="ts">
  import { defaultCairnItemState, hasCairnMechanics } from "../lib/cairn";
  import type { CharacterSheet } from "../lib/types";
  import CairnReadout from "./CairnReadout.svelte";

  type Props = {
    character: CharacterSheet;
    onChange: (character: CharacterSheet) => void;
  };

  const { character, onChange }: Props = $props();

  // The Cairn block stays read-only here. A draft only carries derived
  // mechanics after the backend's one-time backfill runs (on finalize /
  // start_campaign). Surfacing the resolved stats above the editable
  // fields means the player isn't surprised by stats appearing post-
  // finalize. While `source === "unset"` we suppress the block entirely
  // — there's nothing real to show yet.
  const showCairn = $derived(hasCairnMechanics(character.cairn.source));

  function update<K extends keyof CharacterSheet>(key: K, value: CharacterSheet[K]): void {
    onChange({ ...character, [key]: value });
  }

  function updateInventory(
    idx: number,
    key: "name" | "details",
    value: string,
  ): void {
    const next = character.inventory.map((item, itemIdx) =>
      itemIdx === idx ? { ...item, [key]: value } : item,
    );
    update("inventory", next);
  }

  function addItem(): void {
    update("inventory", [
      ...character.inventory,
      {
        id: `item_${crypto.randomUUID().slice(0, 8)}`,
        name: "Unnamed item",
        details: "",
        cairn: defaultCairnItemState(),
      },
    ]);
  }

  function removeItem(idx: number): void {
    update(
      "inventory",
      character.inventory.filter((_, itemIdx) => itemIdx !== idx),
    );
  }
</script>

{#if showCairn}
  <!-- Cairn block sits above the parchment editor as a separate iron-
       voiced surface so the engine voice never bleeds onto narrative
       paper. The block is read-only here on purpose: this pass does not
       expose Cairn mutation controls. -->
  <div class="cairn-preview">
    <CairnReadout cairn={character.cairn} />
  </div>
{/if}

<div class="editor parchment deckle">
  <div class="grid">
    <div>
      <label for="name">Name</label>
      <input
        id="name"
        type="text"
        value={character.name}
        oninput={(event) => update("name", (event.currentTarget as HTMLInputElement).value)}
      />
    </div>
    <div>
      <label for="archetype">Archetype</label>
      <input
        id="archetype"
        type="text"
        value={character.archetype}
        oninput={(event) =>
          update("archetype", (event.currentTarget as HTMLInputElement).value)}
      />
    </div>
  </div>

  <label for="epithet">Epithet</label>
  <textarea
    id="epithet"
    rows="2"
    value={character.epithet}
    oninput={(event) => update("epithet", (event.currentTarget as HTMLTextAreaElement).value)}
  ></textarea>

  <label for="backstory">Backstory</label>
  <textarea
    id="backstory"
    rows="5"
    value={character.backstory}
    oninput={(event) => update("backstory", (event.currentTarget as HTMLTextAreaElement).value)}
  ></textarea>

  <div class="grid">
    <div>
      <label for="drive">Drive</label>
      <textarea
        id="drive"
        rows="2"
        value={character.drive}
        oninput={(event) => update("drive", (event.currentTarget as HTMLTextAreaElement).value)}
      ></textarea>
    </div>
    <div>
      <label for="flaw">Flaw</label>
      <textarea
        id="flaw"
        rows="2"
        value={character.flaw}
        oninput={(event) => update("flaw", (event.currentTarget as HTMLTextAreaElement).value)}
      ></textarea>
    </div>
  </div>

  <label for="condition">Condition</label>
  <input
    id="condition"
    type="text"
    value={character.condition}
    oninput={(event) => update("condition", (event.currentTarget as HTMLInputElement).value)}
  />

  <div class="inventory-head">
    <span class="kicker">Inventory</span>
    <button class="ghost" type="button" onclick={addItem}>Add item</button>
  </div>
  <div class="inventory">
    {#each character.inventory as item, idx (item.id)}
      <div class="item">
        <input
          type="text"
          value={item.name}
          oninput={(event) =>
            updateInventory(idx, "name", (event.currentTarget as HTMLInputElement).value)}
        />
        <textarea
          rows="2"
          value={item.details}
          oninput={(event) =>
            updateInventory(idx, "details", (event.currentTarget as HTMLTextAreaElement).value)}
        ></textarea>
        <button class="ghost" type="button" onclick={() => removeItem(idx)}>Remove</button>
      </div>
    {/each}
  </div>
</div>

<style>
  .editor {
    display: grid;
    gap: 0.7rem;
    color: var(--ink-deep);
  }
  .grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.8rem;
  }
  .inventory-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .inventory {
    display: grid;
    gap: 0.6rem;
  }
  .item {
    display: grid;
    gap: 0.35rem;
    padding: 0.55rem;
    background: rgba(0, 0, 0, 0.06);
    border-left: 2px solid color-mix(in oklab, var(--rust-blood) 50%, transparent);
  }
  .cairn-preview {
    margin-bottom: 0.7rem;
  }
  @media (max-width: 860px) {
    .grid {
      grid-template-columns: 1fr;
    }
  }
</style>
