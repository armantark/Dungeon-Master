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
  import EndBanner from "./components/EndBanner.svelte";
  import Inspector from "./components/Inspector.svelte";
  import SaveLibrary from "./components/SaveLibrary.svelte";
  import SystemMenu from "./components/SystemMenu.svelte";
  import { isCampaignEnded } from "./lib/end-campaign";

  onMount(() => {
    // F-12: bootstrap the save library before fetching state. The
    // bootstrap call decides whether to auto-load the active save's
    // GameState (the steady-state launch) or fall through to the
    // empty-shelf splash. Routing through `bootstrap` instead of the
    // old `refresh()` avoids a 409 round-trip on a fresh install,
    // since `/state` returns 409 when no save is selected.
    void game.bootstrap();
  });

  // F-06 + F-12: a campaign in its terminal state ("ended") still wants
  // the full play-time chrome — strip, character folio, chat feed,
  // inspector — but the Composer is replaced by a read-only End-Banner.
  // The library splashes are exclusive of every other layout: they
  // own the screen until the player resolves them. We classify the
  // layout up-front so the layout tree below stays exhaustive:
  // loading | library-empty | library-selecting | setup | active | ended.
  type LayoutMode =
    | "loading"
    | "library-empty"
    | "library-selecting"
    | "setup"
    | "active"
    | "ended";
  const layout: LayoutMode = $derived.by<LayoutMode>(() => {
    if (game.libraryStatus === "loading") return "loading";
    if (game.libraryStatus === "empty") return "library-empty";
    if (game.libraryStatus === "selecting") return "library-selecting";
    const s = game.state;
    if (s === null) return "loading";
    if (isCampaignEnded(s)) return "ended";
    if (s.campaign_status === "active") return "active";
    return "setup";
  });
  const showPlayChrome = $derived(layout === "active" || layout === "ended");
  const isLibrarySplash = $derived(
    layout === "library-empty" || layout === "library-selecting",
  );
</script>

<div class="app">
  {#if showPlayChrome && game.state}
    <StatusStrip
      chaos={game.state.chaos_factor}
      sceneNumber={game.state.scene_number}
      state={game.state}
    />
  {:else}
    <!--
      Skeleton strip for non-play layouts (character setup, library
      splash, loading). We still surface the SystemMenu here so the
      player can back out of character creation to the save library
      without finalizing a sheet — otherwise "Begin a new campaign"
      becomes a one-way trapdoor until the new sheet is committed.
      The library splashes themselves use this branch too, but the
      menu is harmless there: opening it just keeps the splash on
      screen, and the dropdown items map to the same actions the
      splash already exposes.
    -->
    <div class="strip-skel iron">
      <span class="kicker">Oracle's Ledger</span>
      <SystemMenu />
    </div>
  {/if}

  {#if isLibrarySplash}
    <main class="app__library">
      <SaveLibrary mode={layout === "library-empty" ? "empty" : "selecting"} />
    </main>
  {:else if layout === "setup" && game.state}
    <main class="app__setup">
      {#if game.error}
        <div class="error">{game.error}</div>
      {/if}
      <CharacterSetup state={game.state} />
    </main>
  {:else if (layout === "active" || layout === "ended") && game.state}
    <main class="app__main" class:app__main--ended={layout === "ended"}>
      <CharacterFolio state={game.state} />

      <div class="column">
        {#if game.error}
          <div class="error">{game.error}</div>
        {/if}

        <ChatFeed state={game.state} />

        {#if layout === "ended"}
          <!--
            The Composer is intentionally not mounted in the ended
            layout. We don't disable + grey it out because the player
            has muscle-memory for "click the input → type something",
            and a frozen composer would invite that misclick. Replacing
            it wholesale with the End-Banner makes the lifecycle shift
            unmistakable.
          -->
          <EndBanner state={game.state} />
        {:else}
          <Composer />
        {/if}
      </div>
    </main>
  {:else if game.isLoading}
    <main class="app__main">
      <div class="column">
        <div class="loading parchment deckle">
          <div class="spinner-row">Generating campaign…</div>
          <p class="muted">
            The model is composing the opening scene, threads, NPCs, and
            oracle word banks. First runs can take ~10–30 seconds.
          </p>
        </div>
      </div>
    </main>
  {/if}

  {#if showPlayChrome && game.state}
    <Inspector state={game.state} />
  {/if}
</div>

<style>
  .strip-skel {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
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
  /* The library splash gets the same scrollable container shape as
   * the setup screen (the grid can grow taller than the viewport once
   * the shelf has many tomes), but a slightly wider gutter so the
   * rule of three on the cards reads cleanly on a laptop screen. */
  .app__library {
    overflow-y: auto;
    overflow-x: hidden;
    padding: 1rem 1.2rem 1.4rem;
    min-height: 0;
  }
  /* The ended-archive variant slightly desaturates the play surface so
   * the player's eye registers "this is past tense" before they read
   * the End-Banner copy. We keep contrast on the chat / folio so the
   * archive is still readable; this is a tone shift, not a curtain. */
  .app__main--ended {
    filter: saturate(0.88);
  }
</style>
