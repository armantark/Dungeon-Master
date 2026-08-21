<script lang="ts">
  import ArchitectureMap from "./components/architecture/ArchitectureMap.svelte";
</script>

<svelte:head>
  <title>Dungeon Master — System Map</title>
  <meta
    name="description"
    content="Development-only, source-cited architecture map for Dungeon Master."
  />
</svelte:head>

<main class="architecture-app">
  <ArchitectureMap />
</main>

<style>
  /* The sheet owns the whole window, so nothing of the game's own field shows. */
  .architecture-app {
    min-height: 100dvh;
    background: #c7c4ab;
  }
</style>
