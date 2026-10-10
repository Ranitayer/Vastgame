<script lang="ts">
  import type { Snippet } from 'svelte';
  let { children, id, label, labelledby, inset = false }: { children: Snippet; id?: string; label?: string; labelledby?: string; inset?: boolean } = $props();
</script>
<aside class="details-panel" class:inset {id} aria-label={label} aria-labelledby={labelledby}>
  {@render children()}
</aside>
<style>
  .details-panel { position: relative; height: 100%; min-height: 0; min-width: 0; display: flex; flex-direction: column; border-radius: 24px; overflow: hidden; background: var(--surface-hover); container-type: size; }
  .details-panel.inset { padding: var(--page-margin); gap: var(--page-margin); }
  .details-panel :global(.panel-card) { min-width: 0; padding: var(--page-margin); border-radius: 16px; background: var(--surface); }
</style>
