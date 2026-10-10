<script lang="ts">
  import { invoke } from '@tauri-apps/api/core';
  import { tick } from 'svelte';
  import Button from '../components/Button.svelte';
  import Dropdown from '../components/Dropdown.svelte';
  import ScrollArea from '../components/ScrollArea.svelte';
  import { ensureLibrary } from '../library/catalog.svelte';
  import type { Game } from '../library/types';
  import type { Host } from '../hosts/types';
  import { launch, play, connect, shutdown, useSession, type RestoredSession, type LaunchError } from '../session/launch.svelte';
  import SessionCard from './SessionCard.svelte';
  import SessionDetails from './SessionDetails.svelte';
  import { history, refreshSessions } from './catalog.svelte';
  import { sessionState, type SessionRecord } from './types';
  let { active }: { active: boolean } = $props();
  let pending = $state('');
  let now = $state(Date.now());
  let period = $state(''), status = $state(''), order = $state('');
  let selected = $state<SessionRecord | null>(null);
  $effect(() => { history.erased; selected = null; });
  const selectedRecord = $derived(selected ? history.catalog?.sessions.find(record => record.id === selected?.id) ?? selected : null);
  const periods = [{ value: '1', label: 'Past day' }, { value: '3', label: 'Past 3 days' }, { value: '7', label: 'Past week' }, { value: '30', label: 'Past month' }, { value: '365', label: 'Past year' }];
  const statuses = ['Starting', 'Running', 'Failed', 'Retained', 'Shutdown'];
  const orders = [{ value: 'oldest', label: 'Oldest first' }, { value: 'highest-cost', label: 'Highest cost' }, { value: 'lowest-cost', label: 'Lowest cost' }, { value: 'longest-time', label: 'Longest time' }, { value: 'shortest-time', label: 'Shortest time' }];
  const query = $derived({ days: Number(period) || 0, status: status || 'All', order: order || 'newest' });
  async function closeDetails() {
    const id = selectedRecord?.id;
    selected = null;
    await tick();
    (document.getElementById(`session-card-${id}`) ?? document.getElementById('tab-sessions'))?.focus({ preventScroll: true });
  }
  $effect(() => {
    if (!active) return;
    void ensureLibrary();
    launch.status; launch.instanceId; launch.phase; launch.progress?.active;
    const selected = query;
    const timer = setTimeout(() => void refreshSessions(selected), 100);
    return () => clearTimeout(timer);
  });
  const ticking = $derived(active && (!!history.catalog?.sessions.some(record => record.game_active_since && !record.ended_at) || !!(selectedRecord?.started_at && !selectedRecord.ended_at)));
  $effect(() => {
    now = Date.now();
    if (!ticking) return;
    const timer = setInterval(() => now = Date.now(), 1000);
    return () => clearInterval(timer);
  });
  async function act(record: SessionRecord, stop: boolean): Promise<string> {
    if (pending) return 'Another session operation is active';
    if (stop && record.job_id === launch.jobId && launch.instanceId) { shutdown(); return ''; }
    if (launch.busy || launch.connecting || launch.stopping) return 'Another rig operation is active – check Logs on Home';
    pending = record.id;
    try {
      const result = await invoke<{ error?: LaunchError; session?: { launch: RestoredSession | null; game?: Game; rig?: Host; max_price?: number } }>('prepare_session', { sessionId: record.id, shutdown: stop });
      if (result.error) return result.error.message;
      const prepared = result.session;
      if (!prepared) return 'Session data unavailable. Refresh to retry';
      if (launch.busy || launch.connecting || launch.stopping) return 'Another rig operation started – check Home';
      if (prepared.launch) {
        if (launch.instanceId && launch.jobId !== prepared.launch.jobId) return 'Another rig is active. Use Home to manage it first';
        useSession(prepared.launch);
        if (stop) { if (launch.instanceId) shutdown(); else return 'Rig creation is still pending'; return ''; }
        return await connect();
      }
      useSession(null);
      if (stop) return 'Rig already shut down';
      if (!prepared.game || !prepared.rig) return 'Previous rig unavailable. Choose a rig on Home';
      // The existing Play path re-quotes and validates again immediately before rental.
      return await play(prepared.game, prepared.rig, prepared.max_price);
    } catch (error) { return String(error); }
    finally { pending = ''; void refreshSessions(query); }
  }
</script>
{#if active}
<div class="sessions-page">
  <div class="toolbar">
    <Button icon aria-label="Refresh sessions and provider charges" title="Refresh sessions and provider charges" disabled={history.loading || !!pending} onclick={() => void refreshSessions(query, false, true)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5 M20 12a8 8 0 1 0-2 6"/></svg></Button>
    <Dropdown bind:value={period} options={periods} label="Session time range" placeholder="All time"/>
    <Dropdown bind:value={status} options={statuses} label="Session state" placeholder="All states"/>
    <Dropdown bind:value={order} options={orders} label="Sort sessions" placeholder="Newest first"/>
  </div>
  <div class="content" class:with-panel={!!selectedRecord}>
  <ScrollArea label="Session history">
    {#if history.error}<p class="message" role="alert">{history.error}</p>{/if}
    {#if history.catalog?.skipped}<p class="message" role="status">{history.catalog.skipped} unreadable session records skipped.</p>{/if}
    {#if !history.catalog?.sessions.length}<p class="message">{history.loading ? 'Loading sessions…' : period || status ? 'No sessions match these filters.' : 'Your sessions will appear here after a launch.'}</p>{/if}
    <div class="cards">{#each history.catalog?.sessions ?? [] as record (record.id)}<SessionCard {record} {now} selected={selectedRecord?.id === record.id} onselect={() => selected = selectedRecord?.id === record.id ? null : record} busy={!!pending || ((launch.busy || launch.connecting || launch.stopping) && !(record.job_id === launch.jobId && launch.instanceId && ['Running', 'Starting'].includes(sessionState(record))))} onaction={act}/>{/each}</div>
    {#if history.catalog && history.catalog.total > history.catalog.sessions.length}<div class="more"><Button disabled={history.loading} onclick={() => void refreshSessions(query, true)}>Show more</Button></div>{/if}
  </ScrollArea>
  {#if selectedRecord}{#key selectedRecord.id}<SessionDetails record={selectedRecord} {now} onclose={() => void closeDetails()}/>{/key}{/if}
  </div>
</div>
{/if}
<style>
  .sessions-page { height: 100%; min-height: 0; display: grid; grid-template-rows: auto minmax(0, 1fr); gap: var(--page-margin); }
  .toolbar { display: grid; grid-template-columns: var(--button-size) repeat(3, minmax(0, 1fr)); align-items: center; gap: var(--page-margin); width: 100%; max-width: calc(var(--button-size) + 660px + var(--page-margin) * 3); }
  .toolbar :global(.dropdown) { width: 100%; }
  .content { min-width: 0; min-height: 0; height: 100%; display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--page-margin); }
  .content.with-panel { grid-template-columns: minmax(0, 1fr) minmax(0, var(--details-panel-width)); }
  .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(260px, 100%), 260px)); align-items: start; gap: var(--page-margin); }
  .message { margin: 0 0 var(--page-margin); color: var(--text-muted); font-size: 12px; }
  .more { display: flex; justify-content: center; margin-top: var(--page-margin); }
</style>
