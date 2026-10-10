<script lang="ts">
  import SelectedRig from '../hosts/SelectedRig.svelte';
  import type { Host } from '../hosts/types';
  import StartupProgress from './StartupProgress.svelte';
  import { launch, compactPhase } from './launch.svelte';
  let { host, gameId }: { host: Host | null; gameId: string } = $props();
  const active = $derived(launch.gameId === gameId && !!launch.jobId && (launch.busy || launch.status === 'error' || launch.status === 'quote'));
  const rig = $derived(active || launch.instanceId ? launch.rig : host);
  let now = $state(Date.now());
  const timing = $derived(launch.startedAt > 0 && !launch.endedAt);
  $effect(() => {
    now = Date.now();
    if (!timing) return;
    const timer = setInterval(() => now = Date.now(), 1000);
    return () => clearInterval(timer);
  });
  const seconds = $derived(Math.max(0, Math.floor(((launch.endedAt || now) - launch.startedAt) / 1000)));
  const elapsed = $derived([Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60].map(value => String(value).padStart(2, '0')).join(':'));
</script>
<div class="rig-status" class:active role="group" tabindex={active ? 0 : undefined} aria-label={active ? 'Startup progress. Hover or focus to see rig information.' : 'Selected rig'}>
  <div class="content">
    <div class="rig-info">{#if rig}<SelectedRig host={rig} wide/>{:else}<span>{active || launch.instanceId ? 'Rig information unavailable' : 'Choose a rig'}</span>{/if}</div>
    {#if active}<div class="progress" title={launch.phase}>
      {#if launch.progress && launch.status === 'starting'}<StartupProgress progress={launch.progress} busy={launch.busy}/>{:else}<span role="status">{compactPhase()}</span>{/if}
    </div>{/if}
  </div>
  {#if launch.startedAt && launch.jobId}<span class="elapsed" aria-live="off" aria-label={`Session elapsed time: ${elapsed}`} title="Elapsed since Play, including startup and shutdown. This is not billed time.">{elapsed}</span>{/if}
</div>
<style>
  .rig-status { display: flex; align-items: center; width: 100%; height: var(--button-size); min-width: 0; border-radius: 99px; background: var(--surface-hover); overflow: hidden; }
  .content { position: relative; flex: 1; min-width: 0; height: 100%; }
  .elapsed { flex-shrink: 0; padding-right: var(--page-margin); color: var(--text); font-size: 12px; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .rig-info, .progress { position: absolute; inset: 0; }
  .rig-info > span, .progress { display: grid; place-items: center; height: 100%; padding: 0 var(--page-margin); color: var(--text-muted); font-size: 13px; text-align: center; }
  .active .rig-info { visibility: hidden; }
  .active:hover .rig-info, .active:focus .rig-info { visibility: visible; }
  .active:hover .progress, .active:focus .progress { visibility: hidden; }
  .rig-status:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
  .progress > span { max-width: 100%; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
</style>
