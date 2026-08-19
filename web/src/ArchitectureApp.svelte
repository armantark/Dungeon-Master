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
  .architecture-app {
    min-height: 100vh;
    background:
      radial-gradient(circle at 12% 0%, rgba(63, 139, 145, 0.12), transparent 34%),
      radial-gradient(circle at 84% 8%, rgba(104, 120, 143, 0.12), transparent 38%);
  }
</style>
