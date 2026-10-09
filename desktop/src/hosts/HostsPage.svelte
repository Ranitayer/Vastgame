<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import HostCard from './HostCard.svelte';
  import HostDetails from './HostDetails.svelte';
  import HostFilters from './HostFilters.svelte';
  import { hostContinent } from './continents';
  import ScrollArea from '../components/ScrollArea.svelte';
  import { gpuName, location, type Host, type HostCatalog } from './types';
  let { active }: { active: boolean } = $props();
  let catalog = $state<HostCatalog | null>(null);
  let selected = $state<Host | null>(null);
  let loading = $state(false);
  let attempted = $state(false);
  let error = $state('');
  let search = $state('');
  let continent = $state('');
  let sort = $state('');
  let limit = $state<number | null>(null);
  let visible = $state(48);
  const continents = $derived([...new Set((catalog?.offers ?? []).map(host => hostContinent(host.geolocation)).filter(Boolean))].sort());
  const ceiling = $derived(Math.max(0.01, Math.ceil((catalog?.offers ?? []).reduce((max, host) => Math.max(max, host.dph_total), 0) * 100) / 100));
  const matches = $derived((catalog?.offers ?? []).filter(host =>
    (!continent || hostContinent(host.geolocation) === continent) && (limit === null || host.dph_total <= limit) &&
    `${gpuName(host)} ${location(host)} ${host.cpu_name}`.toLowerCase().includes(search.trim().toLowerCase())).sort((a, b) =>
      (sort === 'Highest price' ? b.dph_total - a.dph_total :
       sort === 'Best value' ? (b.score ?? -1) - (a.score ?? -1) : a.dph_total - b.dph_total) ||
      a.dph_total - b.dph_total || a.id - b.id));
  $effect(() => { if (active && !attempted) { attempted = true; void refresh(); } });
  $effect(() => { search; continent; limit; sort; visible = 48; });
  $effect(() => { if (!active || (selected && !matches.some(host => host.id === selected?.id))) selected = null; });
  $effect(() => { if (continent && !continents.includes(continent)) continent = ''; });
  async function refresh() {
    if (loading) return;
    loading = true;
    error = '';
    try {
      catalog = await invoke<HostCatalog>('browse_hosts');
      selected = null;
    } catch (failure) { error = String(failure); }
    finally { loading = false; }
  }
</script>

<svelte:window onkeydown={(event) => { if (active && selected && event.key === 'Escape') { event.preventDefault(); selected = null; } }} />

{#if active}
  <div class="hosts-page">
    <HostFilters bind:search bind:continent bind:limit bind:sort {continents} {ceiling} {loading} onrefresh={refresh}/>
    {#if error}<p class="message" role="alert">{error}{#if catalog} Previous offers are shown; refresh before choosing.{/if}</p>{/if}
    {#if loading && !catalog}<p class="message" role="status">Finding available VM hosts…</p>
    {:else if catalog}
      <p class="count" aria-live="polite">{matches.length} offers · {sort || 'Lowest price'}</p>
      <div class="workspace" class:open={selected !== null}>
        <ScrollArea separated={selected !== null} label="Available hosts">
          {#if matches.length === 0}<p class="message">No matching GPU VM offers.</p>{/if}
          <div class="cards">{#each matches.slice(0, visible) as host (host.id)}<HostCard {host} selected={selected?.id === host.id} onclick={() => selected = selected?.id === host.id ? null : host}/>{/each}</div>
          {#if matches.length > visible}<button class="more" onclick={() => visible += 48}>Show more · {visible} of {matches.length}</button>{/if}
        </ScrollArea>
        <div id="host-details" class="drawer-slot">{#if selected}<HostDetails host={selected} onclose={() => selected = null}/>{/if}</div>
      </div>
    {/if}
  </div>
{/if}

<style>
  .hosts-page { height: 100%; min-height: 0; display: flex; flex-direction: column; gap: var(--page-margin); }
  .count { color: var(--text-muted); font-size: 12px; margin: 0; }
  .workspace { display: grid; flex: 1; min-height: 0; grid-template-columns: minmax(0, 1fr) minmax(0, 0fr); gap: 0; }
  .workspace.open { grid-template-columns: minmax(0, 1fr) minmax(0, 0.6fr); }
  .drawer-slot { min-width: 0; min-height: 0; overflow: hidden; }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 270px), 1fr)); gap: var(--page-margin); }
  .message { color: var(--text-muted); font-size: 14px; line-height: 1.6; margin: 0; }
  .more { display: block; width: auto; height: 40px; margin: 24px auto 0; padding: 0 18px; font: inherit; font-size: 13px; background: var(--surface-hover); color: var(--text); border-radius: 16px; }
  @media (max-width: 760px) { .workspace.open { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); } }
</style>
