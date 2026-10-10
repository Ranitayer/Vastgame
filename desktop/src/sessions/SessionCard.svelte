<script lang="ts">
  import Button from '../components/Button.svelte';
  import Notice from '../components/Notice.svelte';
  import GameArtwork from '../library/GameArtwork.svelte';
  import CountryLabel from '../hosts/CountryLabel.svelte';
  import SessionMenu from './SessionMenu.svelte';
  import SessionStatus from './SessionStatus.svelte';
  import { amount } from '../hosts/types';
  import { library } from '../library/catalog.svelte';
  import { duration, sessionCost, sessionAction, type SessionRecord } from './types';
  let { record, now, busy, selected, onselect, onaction }: { record: SessionRecord; now: number; busy: boolean; selected: boolean; onselect: () => void; onaction: (record: SessionRecord, stop: boolean) => Promise<string> } = $props();
  let notice = $state('');
  let anchor = $state<HTMLButtonElement>();
  const name = $derived(library.catalog?.games.find(game => game.id === record.game_id)?.name || record.game_name || record.game_id || 'Unknown game');
  const action = $derived(sessionAction(record));
  const cost = $derived(sessionCost(record));
  const played = $derived(record.played_ms == null ? null : record.played_ms + (record.game_active_since && !record.ended_at && record.summary_at ? Math.max(0, now - record.summary_at) : 0));
  async function act() { notice = ''; notice = await onaction(record, action.label === 'Shutdown'); }
</script>
<article class="session-card" class:selected aria-label={`Session: ${name}`}>
  <div class="selection"><Button full {selected} id={`session-card-${record.id}`} title={`${name} · ${record.rig?.gpu_name?.replaceAll('_', ' ') || 'GPU unknown'} · ${record.rig?.geolocation?.replaceAll('_', ' ') || 'Country unknown'} · ${cost.text}\n${cost.title}`} aria-label={`View session: ${name}`} aria-pressed={selected} aria-controls={selected ? 'session-details' : undefined} onclick={onselect}><span aria-hidden="true"></span></Button></div>
  <div class="contents">
  <div class="banner"><GameArtwork gameId={record.game_id || ''} {name} kind="banner"/></div>
  <div class="info">
    <div class="row"><h2 title={name}>{name}</h2><span class="time" title="Observed game time; older sessions may not contain this measurement">{duration(played)}</span></div>
    <div class="rig"><CountryLabel value={record.rig?.geolocation || ''}/><p title={record.rig?.gpu_name?.replaceAll('_', ' ')}>{record.rig?.gpu_name?.replaceAll('_', ' ') || 'GPU unknown'} · {amount(record.rig?.gpu_ram ?? null, 'GB', 1024)}</p></div>
    <div class="row"><SessionStatus {record}/><span class="cost" title={cost.title}>{cost.text}</span></div>
    <div class="actions">
      <Button full tone={action.tone} bind:element={anchor} disabled={busy || action.label === 'Starting'} onclick={() => void act()}>{action.label}</Button>
      <SessionMenu id={record.id} {name}/>
      {#if notice}<Notice {anchor} text={notice}/>{/if}
    </div>
  </div>
  </div>
</article>
<style>
  .session-card { position: relative; width: 100%; min-width: 0; align-self: start; border-radius: 24px; overflow: hidden; }
  .selection { position: absolute; inset: 0; }
  .selection :global(.control) { height: 100%; border-radius: 24px; }
  .contents { position: relative; pointer-events: none; }
  .actions :global(button) { pointer-events: auto; }
  .banner { margin: var(--game-card-inset) var(--game-card-inset) 0; border-radius: 16px; overflow: hidden; }
  .banner :global(.artwork.banner) { border-radius: 16px; }
  .banner :global(.banner img) { height: auto; max-height: none; object-fit: contain; border-radius: 16px; }
  .info { padding: var(--game-card-inset); display: flex; flex-direction: column; gap: 10px; }
  .row { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; }
  h2 { margin: 0; min-width: 0; font-size: 13px; font-weight: 600; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  .time, .cost { flex-shrink: 0; font-variant-numeric: tabular-nums; font-size: 11px; color: var(--text-muted); }
  .cost { color: var(--price); font-weight: 700; }
  .rig { display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-muted); min-width: 0; }
  .rig p { margin: 0; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font: inherit; }
  .actions { display: flex; align-items: center; gap: 8px; }
  .actions > :global(.control.full) { flex: 1; min-width: 0; width: auto; }
</style>
