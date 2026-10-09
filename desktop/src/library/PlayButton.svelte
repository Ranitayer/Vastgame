<script lang="ts">
  import { launch } from '../session/launch.svelte';
  import Button from '../components/Button.svelte';
  let { name, busy, connected = false, onclick }: { name: string; busy: boolean; connected?: boolean; onclick: () => void } = $props();
</script>
<Button icon size="large" variant="inverse" title={connected ? 'Vast Connect' : 'Play'} aria-label={busy ? launch.stopping ? 'Shutting down rig' : `${connected ? 'Connecting' : 'Starting'} — ${name}` : `${connected ? 'Vast Connect' : 'Play'} — ${name}`} aria-busy={busy} disabled={busy || launch.restoring} {onclick}>
  {#if busy}<svg class="spinner" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/></svg>{:else if connected}<svg class="connect" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 8a9 9 0 1 0 1 7M20 3v5h-5"/></svg>{:else}<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 11 7-11 7Z"/></svg>{/if}
</Button>
<style>
  svg { width: 24px; height: 24px; fill: currentColor; stroke: none; }
  .connect { fill: none; stroke: currentColor; stroke-width: 2; }
  .spinner { fill: none; stroke: currentColor; stroke-width: 2; stroke-dasharray: 40 17; animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  @media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
</style>
