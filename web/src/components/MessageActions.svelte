<script lang="ts">
  import { game } from "../lib/store.svelte";

  type Props = { eventId: string; visible: boolean };
  const { eventId, visible }: Props = $props();
</script>

{#if visible}
  <div class="actions">
    <button
      class="ghost"
      type="button"
      disabled={game.isLoading}
      onclick={() => void game.regenerateMessage(eventId)}
    >
      Regenerate response
    </button>
  </div>
{/if}

<style>
  .actions {
    display: flex;
    justify-content: flex-end;
    padding-top: 0.2rem;
  }
  .actions button {
    font-size: 0.8rem;
    padding: 0.28rem 0.48rem;
  }
</style>
