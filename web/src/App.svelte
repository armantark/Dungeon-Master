<!--
@component
App — root.

Chat-first layout:
  +------------------------------------------+
  |  StatusStrip (brand · chaos · inspect)   |  <- thin fixed strip
  +------------------------------------------+
  |                                          |
  |              ChatFeed                    |  <- flowing column,
  |  (DM messages, player actions, system)   |     ~72ch wide, scrolls
  |                                          |
  +------------------------------------------+
  |              Composer                    |  <- sticky bottom
  +------------------------------------------+

  Inspector slides in from the right edge on demand.

Left rail rule: only identity + carried things get permanent space.
Everything else remains peekable reference in the Inspector.
-->
<script lang="ts">
  import { onMount } from "svelte";
  import { game } from "./lib/store.svelte";

  import CharacterSetup from "./components/CharacterSetup.svelte";
  import StatusStrip from "./components/StatusStrip.svelte";
  import CharacterFolio from "./components/CharacterFolio.svelte";
  import ChatFeed from "./components/ChatFeed.svelte";
  import Composer from "./components/Composer.svelte";
  import Inspector from "./components/Inspector.svelte";

  onMount(() => {
    void game.refresh();
  });
</script>

<div class="app">
  {#if game.state && game.state.campaign_status === "active"}
    <StatusStrip chaos={game.state.chaos_factor} sceneNumber={game.state.scene_number} />
  {:else}
    <div class="strip-skel iron">
      <span class="kicker">Oracle's Ledger</span>
    </div>
  {/if}

  {#if game.state && game.state.campaign_status !== "active"}
    <main class="app__setup">
      {#if game.error}
        <div class="error">{game.error}</div>
      {/if}
      <CharacterSetup state={game.state} />
    </main>
  {:else}
    <main class="app__main">
      {#if game.state}
        <CharacterFolio state={game.state} />
      {/if}

      <div class="column">
        {#if game.error}
          <div class="error">{game.error}</div>
        {/if}

        {#if game.state}
          <ChatFeed state={game.state} />
          <Composer />
        {:else if game.isLoading}
          <div class="loading parchment deckle">
            <div class="spinner-row">Generating campaign…</div>
            <p class="muted">
              The model is composing the opening scene, threads, NPCs, and
              oracle word banks. First runs can take ~10–30 seconds.
            </p>
          </div>
        {/if}
      </div>
    </main>
  {/if}

  {#if game.state && game.state.campaign_status === "active"}
    <Inspector state={game.state} />
  {/if}
</div>

<style>
  .strip-skel {
    padding: 0.7rem 1.4rem;
  }
  .strip-skel .kicker {
    margin: 0;
  }
  .loading {
    margin: 1.4rem 0;
    padding: 1.6rem 1.8rem;
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  /* Why a separate container: during character creation we want the
   * setup card to use the full inner width with a comfortable max,
   * not be squeezed into the active-play folio rail of .app__main. */
  .app__setup {
    overflow-y: auto;
    overflow-x: hidden;
    padding: 1rem 1.2rem 1.4rem;
    min-height: 0;
  }
</style>
