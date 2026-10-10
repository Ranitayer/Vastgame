<script lang="ts">
  import Button from '../components/Button.svelte';
  import SearchRefresh from '../components/SearchRefresh.svelte';
  import ScrollArea from '../components/ScrollArea.svelte';
  import Dropdown from '../components/Dropdown.svelte';
  import GameCard from '../library/GameCard.svelte';
  import GameDetails from '../library/GameDetails.svelte';
  import type { Game } from '../library/types';
  import { library, ensureLibrary, refreshLibrary } from '../library/catalog.svelte';
  import HostPill from '../hosts/HostPill.svelte';
  import RigStatus from '../session/RigStatus.svelte';
  import { hosts, ensureHosts, refreshHosts } from '../hosts/catalog.svelte';
  import { gpuName, hostSortOptions, hostPriceCeiling, sortHosts, type Host } from '../hosts/types';
  import { hostContinent } from '../hosts/continents';
  import PriceLimit from '../hosts/PriceLimit.svelte';
  import { launch, restoreLaunch } from '../session/launch.svelte';
  import { refreshBalance } from '../account/balance.svelte';
  import { preferences, ensurePreferences } from '../settings/preferences.svelte';

  let { active, selectedRig = $bindable<Host | null>(null) }: { active: boolean; selectedRig?: Host | null } = $props();
  let search = $state('');
  let selectedId = $state('');
  let expanded = $state<number | null>(null);
  let gpu = $state(''), continent = $state(''), sort = $state('');
  let limit = $state<number | null>(null);
  let visibleGames = $state(48);
  const games = $derived((library.catalog?.games ?? []).filter(game => `${game.name} ${game.id}`.toLowerCase().includes(search.trim().toLowerCase())));
  const game = $derived<Game | null>(library.catalog?.games.find(item => item.id === selectedId) ?? (launch.instanceId ? { id: launch.gameId, name: launch.gameName || 'Game', steam_appid: null, packaged: false, required_disk_gb: null, download_bytes: null } : null));
  const available = $derived(hosts.gameId === (game?.id ?? '') ? hosts.catalog?.offers ?? [] : []);
  const gpus = $derived([...new Set(available.map(gpuName))].sort());
  const continents = $derived([...new Set(available.map(host => hostContinent(host.geolocation)).filter(Boolean))].sort());
  const ceiling = $derived(hostPriceCeiling(available));
  const offers = $derived(sortHosts(available.filter(host => (!gpu || gpuName(host) === gpu) && (!continent || hostContinent(host.geolocation) === continent) && (limit === null || host.dph_total <= limit)), sort));
  $effect(() => {
    if (!active) return;
    void ensureLibrary();
    void ensurePreferences();
    preferences.revision;
    const catalog = library.catalog;
    if (catalog && !catalog.games.some(item => item.id === selectedId)) selectedId = catalog.games.find(item => item.id === launch.gameId)?.id ?? catalog.games[0]?.id ?? '';
    if (catalog && preferences.data) void ensureHosts(game?.id ?? '');
  });
  $effect(() => { search; visibleGames = 48; });
  $effect(() => { selectedId; expanded = null; });
  $effect(() => {
    if (hosts.loading || hosts.gameId !== (game?.id ?? '') || !hosts.catalog) return;
    if (gpu && !gpus.includes(gpu)) gpu = '';
    if (continent && !continents.includes(continent)) continent = '';
  });
  $effect(() => { if (expanded !== null && !offers.some(host => host.id === expanded)) expanded = null; });
  async function refresh() {
    await Promise.all([refreshLibrary(), restoreLaunch(true), refreshBalance(true)]);
    await refreshHosts(game?.id ?? '');
  }
</script>

{#if active}
<div class="home">
  <section class="library-column" aria-label="Your games">
    <div class="search"><SearchRefresh bind:search label="home library" placeholder="Find a game" loading={library.loading || hosts.loading} onrefresh={() => void refresh()}/></div>
    <ScrollArea label="Home game library">
      {#if library.error}<p class="message" role="alert">{library.error}</p>{/if}
      {#if library.catalog?.skipped}<p class="message" role="status">{library.catalog.skipped} unreadable game entries skipped.</p>{/if}
      {#if !games.length}<p class="message">{library.loading ? 'Loading your games…' : 'No matching games.'}</p>{/if}
      <div class="games">{#each games.slice(0, visibleGames) as item (item.id)}<GameCard game={item} selected={selectedId === item.id} onclick={() => selectedId = item.id}/>{/each}</div>
      {#if games.length > visibleGames}<div class="more"><Button onclick={() => visibleGames += 48}>Show more</Button></div>{/if}
    </ScrollArea>
  </section>
  <section class="hosts-column" aria-label="Available rigs">
    <div class="host-filters"><Dropdown bind:value={gpu} options={gpus} label="GPU" placeholder="All GPUs"/><Dropdown bind:value={continent} options={continents} label="Continent" placeholder="All continents"/></div>
    <ScrollArea label="Home rigs">
      {#if hosts.error || preferences.error}<p class="message" role="alert">{hosts.error || preferences.error}</p>{/if}
      {#if !offers.length}<p class="message" role="status">{hosts.loading || preferences.loading ? 'Finding available rigs…' : 'No matching rigs.'}</p>{/if}
      <div class="rigs">{#each offers as host (host.id)}<HostPill {host} expanded={expanded === host.id} chosen={selectedRig?.id === host.id} ontoggle={() => expanded = expanded === host.id ? null : host.id} onchoose={() => selectedRig = selectedRig?.id === host.id ? null : host}/>{/each}</div>
    </ScrollArea>
    <div class="host-filters"><Dropdown bind:value={sort} options={hostSortOptions} label="Rank rigs" placeholder="Lowest price" up/><PriceLimit bind:limit {ceiling} disabled={hosts.loading}/></div>
  </section>
  <section class="game-column" aria-label="Selected game">
    <div class="rig-header"><RigStatus host={selectedRig} gameId={game?.id ?? ''}/></div>
    <div class="game-panel" id="game-details">{#if game}<GameDetails {game} {selectedRig}/>{:else}<p class="message">Choose a game from your library.</p>{/if}</div>
  </section>
</div>
{/if}
<style>
  .home { display: grid; grid-template-columns: minmax(0, 1.31248fr) minmax(0, 0.84252fr) minmax(0, var(--details-panel-width)); gap: var(--page-margin); height: 100%; min-height: 0; }
  section { min-width: 0; min-height: 0; }
  .library-column { display: grid; grid-template-rows: auto minmax(0, 1fr); gap: var(--page-margin); }
  .search { display: flex; justify-content: center; min-width: 0; }
  .games { --game-card-width: 200px; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); align-items: start; width: 100%; max-width: calc(var(--game-card-width) * 3 + var(--page-margin) * 2); margin-inline: auto; gap: var(--page-margin); }
  .hosts-column { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; gap: var(--page-margin); }
  .host-filters { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); align-items: center; gap: var(--page-margin); }
  .host-filters :global(.dropdown) { width: 100%; }
  .rigs { display: grid; gap: var(--page-margin); }
  .game-column { display: grid; grid-template-rows: auto minmax(0, 1fr); gap: var(--page-margin); }
  .rig-header { display: flex; align-items: center; height: var(--button-size); min-width: 0; }
  .game-panel { min-height: 0; min-width: 0; }
  .message { margin: 0 0 var(--page-margin); color: var(--text-muted); font-size: 12px; overflow-wrap: anywhere; }
  .more { display: flex; justify-content: center; margin-top: var(--page-margin); }
</style>
