<!--
@component
CharacterFolio — persistent left rail for who you are and what you carry.

This sits beside the chat because identity + inventory are not "deep
inspector" data. They are the immediate play affordances the player
checks before declaring an action.

The Cairn mechanical readout (HP / STR / DEX / WIL / burden / statuses /
skills+abilities) sits between the identity plate and the inventory list
because those numbers are what the player consults *before* deciding
whether their next action is a save attempt or a freeform action. The
readout is purely read-only here; no buttons mutate state from this rail.
-->
<script lang="ts">
  import {
    defaultCairnCharacterState,
    defaultCairnItemState,
    hasCairnMechanics,
    itemPowerSummary,
    itemPowerTitle,
    itemTagLabels,
  } from "../lib/cairn";
  import type {
    CharacterSheet,
    GameState,
    InventoryItem,
    PartyMember,
  } from "../lib/types";
  import CairnReadout from "./CairnReadout.svelte";

  type Props = { state: GameState };
  const { state: gs }: Props = $props();

  type FolioActor = {
    id: string;
    role: "player" | PartyMember["kind"];
    tabLabel: string;
    sheet: CharacterSheet;
    member: PartyMember | null;
  };

  let selectedActorId = $state("player");

  const fallbackCharacter = $derived.by<CharacterSheet>(() => ({
    name: "Unnamed wanderer",
    archetype: "Unknown wanderer",
    epithet: gs.player_notes,
    backstory: gs.player_notes,
    drive: "Survive the next turning of the wheel.",
    flaw: "Too much remains undefined.",
    condition: "Unrecorded.",
    inventory: [],
    cairn: defaultCairnCharacterState(),
  }));

  const displayLabel = (sheet: CharacterSheet, fallback: string): string => {
    const name = sheet.name.trim();
    if (name !== "") return name;
    const epithet = sheet.epithet.trim();
    if (epithet !== "") return epithet;
    return fallback;
  };

  const roleLabel = (role: FolioActor["role"]): string => {
    switch (role) {
      case "player":
        return "Protagonist";
      case "companion":
        return "Companion";
      case "hireling":
        return "Hireling";
      case "animal":
        return "Animal";
    }
  };

  const actors = $derived.by<FolioActor[]>(() => {
    const playerSheet = gs.character ?? fallbackCharacter;
    const party = gs.party_members
      .filter((member) => member.active)
      .map((member) => ({
        id: member.id,
        role: member.kind,
        tabLabel: displayLabel(member.sheet, roleLabel(member.kind)),
        sheet: member.sheet,
        member,
      }));

    return [
      {
        id: "player",
        role: "player",
        tabLabel: displayLabel(playerSheet, "You"),
        sheet: playerSheet,
        member: null,
      },
      ...party,
    ];
  });

  $effect(() => {
    if (!actors.some((actor) => actor.id === selectedActorId)) {
      selectedActorId = "player";
    }
  });

  const selectedActor = $derived.by<FolioActor>(() => {
    return actors.find((actor) => actor.id === selectedActorId) ?? actors[0]!;
  });

  const character = $derived(selectedActor.sheet);

  const inventory = $derived.by<InventoryItem[]>(() => {
    if (character.inventory.length > 0) return character.inventory;
    return [
      {
        id: "empty",
        name: "No tracked gear",
        details: "Inventory has not been established for this campaign yet.",
        cairn: defaultCairnItemState(),
      },
    ];
  });

  // Why a derived gate: the backend only populates real Cairn mechanics
  // after one-time backfill on finalize / start_campaign. Until then
  // `cairn.source === "unset"` and the numbers are placeholders we
  // shouldn't pretend are canonical.
  const showCairn = $derived(hasCairnMechanics(character.cairn.source));

  const isPrimaryWeapon = (item: InventoryItem): boolean =>
    character.cairn.primary_weapon_item_id === item.id;
</script>

<aside class="folio iron" aria-label="Character sheet and inventory">
  <!--
    `.folio__layout` is a separate grid container nested inside
    `.folio` because container queries cannot restyle the container
    element itself, only its descendants. `.folio` carries the sticky
    positioning, fixed height, and `container-type: inline-size`;
    `.folio__layout` carries the actual grid template, which the
    @container rule below toggles between a 4-row single column
    (narrow rail) and a 2-column identity / ledger split (wide rail).

    The inner column wrappers collapse via `display: contents` in the
    narrow mode so the four real sections (plate, condition,
    mechanics, inventory) flow as direct grid children and keep the
    original vertical stack.
  -->
  <div class="folio__layout">
  <div class="folio__col folio__col--identity">
    {#if actors.length > 1}
      <nav class="party-tabs" aria-label="Party folio">
        {#each actors as actor (actor.id)}
          <button
            class:party-tabs__button--active={actor.id === selectedActor.id}
            type="button"
            aria-pressed={actor.id === selectedActor.id}
            onclick={() => {
              selectedActorId = actor.id;
            }}
          >
            <span class="party-tabs__role pixel">{roleLabel(actor.role)}</span>
            <span class="party-tabs__name">{actor.tabLabel}</span>
          </button>
        {/each}
      </nav>
    {/if}

    <div class="plate">
      <span class="kicker">{roleLabel(selectedActor.role)} · {character.archetype}</span>
      <h2>{character.name}</h2>
      <p class="epithet">{character.epithet || character.backstory || gs.player_notes}</p>
      {#if selectedActor.member?.loyalty || selectedActor.member?.notes}
        <p class="party-note">
          {selectedActor.member.loyalty || selectedActor.member.notes}
        </p>
      {/if}
    </div>

    <section class="condition">
      <div class="condition__cell">
        <span class="kicker">Condition</span>
        <p>{character.condition}</p>
      </div>
      <div class="condition__cell">
        <span class="kicker">Drive</span>
        <p>{character.drive}</p>
      </div>
    </section>
  </div>

  <div class="folio__col folio__col--ledger">
    {#if showCairn}
      <section class="mechanics">
        <CairnReadout cairn={character.cairn} />
      </section>
    {/if}

    <section class="inventory">
      <span class="kicker">Inventory</span>
      <ul>
      {#each inventory as item (item.id)}
        {@const tagLabels = itemTagLabels(item.cairn)}
        {@const showTags = showCairn && tagLabels.length > 0}
        {@const powerTitle = itemPowerTitle(item.cairn.power)}
        {@const powerSummary = itemPowerSummary(item.cairn.power)}
        <li class:item--equipped={item.cairn.equipped}>
          <div class="item__head">
            <strong>{item.name}</strong>
            {#if showCairn && item.cairn.equipped}
              <span class="item__badge pixel" aria-label="Equipped">Equipped</span>
            {/if}
            {#if showCairn && isPrimaryWeapon(item)}
              <span class="item__badge item__badge--primary pixel" aria-label="Primary weapon">
                Primary
              </span>
            {/if}
          </div>
          {#if item.details}
            <span class="item__details">{item.details}</span>
          {/if}
          {#if showCairn && powerTitle !== null}
            <div class="item__power" aria-label="Item power">
              <span class="item__power-title pixel">{powerTitle}</span>
              {#if powerSummary !== null}
                <span class="item__power-summary">{powerSummary}</span>
              {/if}
            </div>
          {/if}
          {#if showTags}
            <ul class="item__tags" aria-label="Item tags">
              {#each tagLabels as label, idx (idx)}
                <li class="pixel">{label}</li>
              {/each}
            </ul>
          {/if}
          {#if showCairn}
            {@const die = item.cairn.weapon_damage_die}
            {@const armor = item.cairn.armor_bonus}
            {@const uses = item.cairn.uses}
            {@const slots = item.cairn.slots}
            {@const power = item.cairn.power}
            {#if die !== null || armor > 0 || uses !== null || slots !== 1 || power?.adds_fatigue || power?.requires_wil_save_in_danger || power?.consumed_on_use}
              <ul class="item__stats pixel" aria-label="Item mechanics">
                {#if die !== null}
                  <li>Dmg d{die}</li>
                {/if}
                {#if armor > 0}
                  <li>+{armor} armor</li>
                {/if}
                {#if uses !== null}
                  <li>Uses {uses}</li>
                {/if}
                {#if slots !== 1}
                  <li>{slots} slots</li>
                {/if}
                {#if power?.adds_fatigue}
                  <li>+Fatigue</li>
                {/if}
                {#if power?.requires_wil_save_in_danger}
                  <li>WIL in danger</li>
                {/if}
                {#if power?.consumed_on_use}
                  <li>Consumed</li>
                {/if}
              </ul>
            {/if}
          {/if}
        </li>
      {/each}
      </ul>
    </section>
  </div>
  </div>
</aside>

<style>
  .folio {
    align-self: start;
    position: sticky;
    top: 1rem;
    height: calc(100vh - 7.2rem);
    min-height: 0;
    overflow: hidden;
    border: var(--rule-hair);
    box-shadow: var(--shadow-deep), var(--shadow-leather);
    /*
     * Establish a containment context so the inner layout reacts to
     * the rail's own width rather than the viewport. The rail can be
     * the same logical width on a narrow window and a wide one
     * depending on `clamp()` math in app.css, so viewport media
     * queries would lie about what is actually available here.
     */
    container-type: inline-size;
    container-name: folio;
  }
  /*
   * The actual grid lives on the inner layout because @container
   * queries can only target descendants of the container element,
   * not the container itself. Narrow mode is a 4-row single column;
   * the @container rule further down flips this into a 2-column
   * identity / ledger split when the folio has width to spare.
   */
  .folio__layout {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto auto auto auto minmax(0, 1fr);
    height: 100%;
    min-height: 0;
  }
  /*
   * In narrow mode, the column wrappers disappear from the layout via
   * `display: contents` so the four real sections (plate, condition,
   * mechanics, inventory) become direct grid children of
   * `.folio__layout` and use the original 4-row vertical stack. In
   * wide mode the @container query below promotes them into real
   * flex columns.
   */
  .folio__col {
    display: contents;
  }
  .party-tabs,
  .plate,
  .condition,
  .mechanics,
  .inventory {
    padding: 0.7rem 0.8rem;
    border-bottom: var(--rule-hair);
  }
  .party-tabs {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    align-content: flex-start;
    overflow-y: auto;
    max-height: 7.2rem;
    scrollbar-gutter: stable;
    background:
      linear-gradient(
        180deg,
        color-mix(in oklab, var(--ink-bruise) 34%, transparent),
        rgba(0, 0, 0, 0.12)
      );
  }
  .party-tabs button {
    flex: 1 1 7.5rem;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.12rem;
    padding: 0.35rem 0.45rem;
    text-align: left;
    border-color: color-mix(in oklab, var(--gold-tarnished) 38%, transparent);
    background:
      linear-gradient(
        180deg,
        color-mix(in oklab, var(--ink-deep) 92%, var(--rust-blood)),
        rgba(0, 0, 0, 0.38)
      );
    color: var(--paper-bone);
  }
  .party-tabs button:hover,
  .party-tabs button:focus-visible {
    border-color: var(--gold-tarnished);
    color: var(--paper-warm);
  }
  .party-tabs button.party-tabs__button--active {
    border-color: var(--gold-bright);
    color: var(--paper-warm);
    box-shadow:
      inset 2px 0 0 var(--gold-bright),
      inset 0 0 18px color-mix(in oklab, var(--gold-tarnished) 18%, transparent);
  }
  .party-tabs__role {
    color: var(--gold-tarnished);
    font-size: 0.62rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }
  .party-tabs__name {
    width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--font-display);
    font-size: 0.9rem;
    line-height: 1;
    text-transform: none;
    letter-spacing: 0.02em;
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
  .epithet {
    display: -webkit-box;
    line-clamp: 4;
    -webkit-line-clamp: 4;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .party-note {
    margin: 0.45rem 0 0;
    padding-left: 0.5rem;
    border-left: 2px solid color-mix(in oklab, var(--green-verdigris) 60%, transparent);
    color: var(--paper-stained);
    font-size: 0.8rem;
    line-height: 1.28;
  }
  /*
   * Condition + Drive are always vertically stacked. The clamp keeps
   * the section's worst-case height bounded so the inventory section
   * below it doesn't get pushed offscreen on a narrow rail. In
   * two-column folio mode (see the @container rule further down) the
   * clamp is removed because the section then lives in its own tall
   * column with room for the full text.
   */
  .condition {
    display: grid;
    grid-template-columns: minmax(0, 1fr);
    gap: 0.55rem;
  }
  .condition__cell {
    display: flex;
    flex-direction: column;
    gap: 0.18rem;
    min-width: 0;
  }
  .condition__cell .kicker {
    margin: 0;
  }
  .condition p {
    display: -webkit-box;
    line-clamp: 3;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
  }
  .mechanics {
    /* The CairnReadout brings its own iron-flavored panel; this wrapper
       just maintains rail rhythm. */
    padding: 0.6rem 0.8rem;
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
    display: flex;
    flex-direction: column;
    gap: 0.18rem;
  }
  .inventory li.item--equipped {
    border-left-color: var(--gold-bright);
  }
  .item__head {
    display: flex;
    align-items: baseline;
    gap: 0.4rem;
    flex-wrap: wrap;
  }
  .inventory strong {
    font-family: var(--font-display);
    font-size: 0.98rem;
    color: var(--paper-warm);
    font-weight: 400;
    line-height: 1.05;
    flex: 1 1 auto;
    min-width: 0;
  }
  .item__badge {
    font-size: 0.65rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--gold-bright);
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 50%, transparent);
    padding: 0.05rem 0.35rem;
    background: rgba(0, 0, 0, 0.35);
  }
  .item__badge--primary {
    color: var(--paper-warm);
    border-color: var(--gold-bright);
  }
  .item__details {
    color: var(--paper-shadow);
    font-size: 0.82rem;
    line-height: 1.32;
  }
  .item__power {
    margin-top: 0.22rem;
    padding: 0.35rem 0.45rem;
    border: 1px solid color-mix(in oklab, var(--green-verdigris) 36%, transparent);
    background:
      linear-gradient(
        120deg,
        color-mix(in oklab, var(--green-verdigris) 18%, transparent),
        rgba(0, 0, 0, 0.26)
      );
    display: flex;
    flex-direction: column;
    gap: 0.16rem;
  }
  .item__power-title {
    color: var(--gold-bright);
    font-size: 0.68rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .item__power-summary {
    color: var(--paper-bone);
    font-size: 0.78rem;
    line-height: 1.25;
  }
  .item__tags {
    list-style: none;
    padding: 0;
    margin: 0.15rem 0 0;
    display: flex;
    flex-wrap: wrap;
    gap: 0.22rem;
  }
  .item__tags li {
    border: 1px solid color-mix(in oklab, var(--gold-tarnished) 45%, transparent);
    background: rgba(0, 0, 0, 0.4);
    color: var(--gold-tarnished);
    font-size: 0.65rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    padding: 0.05rem 0.35rem;
    /* Override the parent .inventory li styles. */
    display: inline-block;
    flex-direction: initial;
    border-left-width: 1px;
    gap: 0;
  }
  .item__stats {
    list-style: none;
    padding: 0;
    margin: 0.18rem 0 0;
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
    color: var(--gold-tarnished);
    font-size: 0.72rem;
    letter-spacing: 0.04em;
  }
  .item__stats li {
    border: 0;
    background: transparent;
    padding: 0;
    margin: 0;
    color: var(--gold-tarnished);
    border-left: 0;
    /* Override the parent .inventory li styles. */
    display: inline;
    flex-direction: initial;
    gap: 0;
  }

  /*
   * Wide-rail layout. When the folio's own content width crosses
   * ~280px (i.e. as soon as the rail has any breathing room past
   * its lower clamp, which corresponds roughly to ~750px+ viewports
   * given the `clamp(296px, 40vw, 720px)` rule in app.css) the rail
   * flips into a two-column shape: identity (plate + condition/drive)
   * on the left, ledger (mechanics readout + inventory) on the right.
   *
   * This is the layout the user actually wants — a true two-column
   * rail rather than a stacked single column. The threshold is
   * deliberately aggressive because removing the 3-line clamp on
   * condition / drive matters more than maximizing per-column inline
   * space; each column is still wider than ~135px even at the lower
   * clamp, which is enough for body text to wrap legibly.
   *
   * The vertical rule between the columns replaces the inter-section
   * horizontal rules that would otherwise float above empty space at
   * the bottom of the shorter (identity) column.
   */
  @container folio (min-width: 280px) {
    .folio__layout {
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      grid-template-rows: minmax(0, 1fr);
    }
    .folio__col {
      display: flex;
      flex-direction: column;
      min-height: 0;
      min-width: 0;
    }
    .folio__col--identity {
      border-right: var(--rule-hair);
      overflow: hidden;
    }
    .folio__col--ledger {
      overflow: hidden;
    }
    .folio__col--ledger .mechanics {
      flex: 0 0 auto;
    }
    .folio__col--ledger .inventory {
      flex: 1 1 auto;
      min-height: 0;
    }
    /*
     * Drop the trailing horizontal rule on the last section in each
     * column; without this, the rule would draw a stranded line above
     * the empty space at the bottom of the shorter column.
     */
    .folio__col--identity > .condition,
    .folio__col--ledger > .inventory {
      border-bottom: 0;
    }
    /*
     * In wide mode the condition section owns enough vertical room to
     * show full text, so the 3-line clamp that protects the narrow
     * layout from squeezing inventory off the rail is unnecessary.
     */
    .condition p {
      display: block;
      -webkit-line-clamp: unset;
      line-clamp: unset;
      -webkit-box-orient: initial;
      overflow: visible;
    }
  }
</style>
