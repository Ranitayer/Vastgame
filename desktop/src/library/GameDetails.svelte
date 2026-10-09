<script lang="ts">
  import Notice from '../components/Notice.svelte';
  import { launch, play, connect } from '../session/launch.svelte';
  import type { Host } from '../hosts/types';
  import { library } from './catalog.svelte';
  import GameArtwork from './GameArtwork.svelte';
  import ShutdownButton from '../session/ShutdownButton.svelte';
  import PlayButton from './PlayButton.svelte';
  import GameLogs from './GameLogs.svelte';
  import { gameSize, type Game } from './types';
  import { gameDetails, type SteamDetails } from './details';
  let { game, selectedRig }: { game: Game; selectedRig: Host | null } = $props();
  let metadata = $state<SteamDetails | null>(null);
  let loading = $state(false);
  let logsOpen = $state(false);
  let notice = $state('');
  let playAnchor = $state<HTMLDivElement>();
  const activeRig = $derived(!!launch.instanceId);
  const connected = $derived(activeRig && (launch.gameRunning || launch.status === 'ready'));
  $effect(() => { game.id; notice = ''; });
  $effect(() => { game.id; logsOpen = false; });
  async function requestPlay() { const id = game.id; notice = ''; const message = await play(game, selectedRig); if (game.id === id) notice = message; }
  async function requestConnect() { const id = game.id; notice = ''; const message = await connect(); if (game.id === id) notice = message; }
  const reviews = $derived(metadata?.reviews);
  const approval = $derived(reviews?.total ? Math.round(reviews.positive / reviews.total * 100) : 0);
  $effect(() => {
    library.revision;
    const appid = game.steam_appid;
    let current = true;
    metadata = null; loading = !!appid;
    if (appid) void gameDetails(appid).then(result => { if (current) { metadata = result; loading = false; } });
    return () => { current = false; };
  });
</script>
<aside class="details" aria-labelledby="game-title">
  <div class="hero">
    <GameArtwork name={game.name} appid={game.steam_appid} kind="banner"/><div class="fade"></div>
    <div class="play" bind:this={playAnchor}><PlayButton name={activeRig ? launch.gameName : game.name} {connected} busy={(activeRig || launch.gameId === game.id) && (launch.busy || launch.connecting)} onclick={() => void (connected ? requestConnect() : requestPlay())}/>{#if activeRig}<ShutdownButton/>{/if}{#if notice}<Notice anchor={playAnchor} text={notice}/>{:else if launch.gameId === game.id && launch.status === 'error'}<Notice anchor={playAnchor} text={launch.error?.message || launch.phase} detail={launch.error ? `[${launch.error.code}] ${launch.error.message}` : launch.phase}/>{/if}</div>
  </div>
    <div class="information">
      <div class="heading">
      <h2 id="game-title" title={game.name}>{game.name}</h2>
    <div class="review" aria-label="Steam user reviews" title={reviews?.total ? `${approval}% positive · ${reviews.total.toLocaleString()} Steam reviews` : ''}>
      {#if reviews?.total}<strong>{reviews.sentiment || 'User reviews'}</strong><span class="approval">{approval}%</span>
      {:else}<span>{loading ? 'Loading reviews…' : reviews ? 'No reviews yet' : 'Reviews unavailable'}</span>{/if}
    </div>
      </div>
      <section class="description card" aria-label="About the game">
        <header class="about-heading"><h3>About</h3><span aria-label={`Download size: ${gameSize(game.download_bytes)}`} title="Download size">{gameSize(game.download_bytes)}</span></header>
        <p title={metadata?.description}>{metadata?.description || (loading ? 'Loading description…' : 'Description unavailable')}</p>
      </section>
    </div>
  <div class="log-footer"><GameLogs bind:open={logsOpen} lines={activeRig || launch.gameId === game.id ? launch.logs : []}/></div>

</aside>
<style>
  .details { position: relative; height: 100%; min-height: 0; display: flex; flex-direction: column; border-radius: 24px; overflow: hidden; background: var(--surface-hover); container-type: size; }
  .hero { position: relative; flex: 0 0 auto; }
  .fade { position: absolute; inset: 0; background: linear-gradient(to bottom, transparent 45%, var(--surface-hover) 100%); pointer-events: none; }
  .heading { display: flex; align-items: center; gap: var(--page-margin); min-width: 0; }
  .heading h2 { flex: 1; min-width: 0; }
  .play { position: absolute; top: var(--page-margin); left: var(--page-margin); display: flex; align-items: center; gap: var(--page-margin); max-width: calc(100% - var(--page-margin) * 2); }
  .review { flex: 0 1 auto; max-width: 55%; display: flex; align-items: center; justify-content: center; gap: 6px; min-height: 30px; padding: 6px 10px; border-radius: 99px; background: var(--accent); color: var(--text); font-size: 11px; line-height: 1; }
  .review strong { display: flex; align-items: center; font-size: inherit; font-weight: 600; line-height: 1.2; }
  .approval { white-space: nowrap; }
  .information { position: relative; flex: 0 0 auto; min-height: 0; padding: var(--page-margin) var(--page-margin) 0; display: flex; flex-direction: column; gap: var(--page-margin); }
  .log-footer { flex: 1; min-height: calc(var(--button-size) + var(--page-margin) * 3); padding: var(--page-margin); }
  h2 { margin: 0; font-size: 21px; font-weight: 600; overflow-wrap: anywhere; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden; }
  .card { padding: var(--page-margin); border-radius: 16px; background: var(--surface); }
  .about-heading { display: flex; align-items: center; justify-content: space-between; gap: var(--page-margin); margin-bottom: 8px; }
  .about-heading span { flex-shrink: 0; font-size: 12px; color: var(--text-muted); }
  h3 { margin: 0; font-size: 12px; font-weight: 600; }
  p { margin: 0; font-size: 12px; line-height: 1.5; color: var(--text-muted); display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 5; overflow: hidden; }
  @container (max-height: 650px) { p { -webkit-line-clamp: 3; } h2 { font-size: 18px; } }
  @container (max-height: 480px) { .hero :global(.banner img) { max-height: 72px; } p { -webkit-line-clamp: 1; font-size: 11px; line-height: 1.4; } }
  @container (max-width: 340px) { .review { gap: 4px; font-size: 10px; padding: 5px 8px; } .approval { display: none; } h2 { font-size: 16px; } }
</style>
