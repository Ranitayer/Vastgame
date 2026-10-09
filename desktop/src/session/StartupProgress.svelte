<script lang="ts">
  import type { StartupProgress } from './progress';
  let { progress, busy }: { progress: StartupProgress; busy: boolean } = $props();
  const stage = $derived(progress.stages.find(item => item.id === progress.active));
  let now = $state(Date.now());
  $effect(() => { now = Date.now(); if (!busy) return; const timer = setInterval(() => now = Date.now(), 1000); return () => clearInterval(timer); });
  const fresh = $derived(busy && stage?.measured_at !== undefined && now / 1000 - stage.measured_at <= 10);
  const size = (bytes: number) => `${(bytes / 1024 ** 3).toFixed(1)} GiB`;
  const duration = (seconds: number) => `${Math.floor(Math.ceil(seconds) / 60)}m ${Math.ceil(seconds) % 60}s`;
</script>
{#if stage}
<section class="startup" aria-label="Startup progress">
  <strong>{stage.name}</strong>
  <div class="measurements" role="status">
    {#if stage.total !== undefined && stage.bytes !== undefined}<span>{stage.percent}% · {size(stage.bytes)} / {size(stage.total)}</span>{:else}<span>{stage.state === 'error' ? 'Stage failed — check Logs' : stage.action || 'Waiting for confirmation'}</span>{/if}
    {#if fresh && stage.eta !== undefined}<span>ETA {duration(stage.eta)}</span>{/if}
  </div>
</section>
{/if}
<style>
  .startup { display: flex; align-items: center; justify-content: center; gap: 8px; width: 100%; min-width: 0; font-size: 11px; white-space: nowrap; }
  strong { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .measurements { display: flex; align-items: center; gap: 8px; min-width: 0; font-size: 10px; color: var(--text-muted); }
  .measurements span { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
</style>
