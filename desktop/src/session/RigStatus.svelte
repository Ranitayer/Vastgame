<script lang="ts">
  import SelectedRig from '../hosts/SelectedRig.svelte';
  import type { Host } from '../hosts/types';
  import StartupProgress from './StartupProgress.svelte';
  import { launch, compactPhase } from './launch.svelte';
  let { host, gameId }: { host: Host | null; gameId: string } = $props();
  const active = $derived(launch.gameId === gameId && !!launch.jobId && (launch.busy || launch.status === 'error' || launch.status === 'quote'));
  const rig = $derived(active ? launch.rig : host);
</script>
<div class="rig-status" class:active role="group" tabindex={active ? 0 : undefined} aria-label={active ? 'Startup progress. Hover or focus to see rig information.' : 'Selected rig'}>
  <div class="rig-info">{#if rig}<SelectedRig host={rig} wide/>{:else}<span>{active ? 'Rig information unavailable' : 'Choose a rig'}</span>{/if}</div>
  {#if active}<div class="progress" title={launch.phase}>
    {#if launch.progress && launch.status === 'starting'}<StartupProgress progress={launch.progress} busy={launch.busy}/>{:else}<span role="status">{compactPhase()}</span>{/if}
  </div>{/if}
</div>
<style>
  .rig-status { position: relative; width: 100%; height: var(--button-size); min-width: 0; border-radius: 99px; background: var(--surface-hover); overflow: hidden; }
  .rig-info, .progress { position: absolute; inset: 0; }
  .rig-info > span, .progress { display: grid; place-items: center; height: 100%; padding: 0 var(--page-margin); color: var(--text-muted); font-size: 13px; text-align: center; }
  .active .rig-info { visibility: hidden; }
  .active:hover .rig-info, .active:focus .rig-info { visibility: visible; }
  .active:hover .progress, .active:focus .progress { visibility: hidden; }
  .rig-status:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
  .progress > span { max-width: 100%; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
</style>
