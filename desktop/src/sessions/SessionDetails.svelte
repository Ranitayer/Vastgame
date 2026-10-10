<script lang="ts">
  import { tick } from 'svelte';
  import Button from '../components/Button.svelte';
  import DetailsPanel from '../components/DetailsPanel.svelte';
  import Notice from '../components/Notice.svelte';
  import LogOutput from '../components/LogOutput.svelte';
  import { copyText } from '../components/clipboard';
  import CountryLabel from '../hosts/CountryLabel.svelte';
  import { amount } from '../hosts/types';
  import { library } from '../library/catalog.svelte';
  import { formatLog, type LogEntry } from '../session/logs';
  import SessionStatus from './SessionStatus.svelte';
  import { readLogs, readEvents, copySessionLogs, copySessionEvents, type SessionEvent } from './archive';
  import { duration, type SessionRecord } from './types';
  import { sessionEvents } from './events';
  let { record, now, onclose }: { record: SessionRecord; now: number; onclose: () => void } = $props();
  let details = $state<SessionRecord | null>(null);
  let entries = $state<SessionEvent[]>([]), cursor = $state<number | null>(null);
  let transitions = $state<SessionEvent[] | undefined>(), eventCursor = $state<number | null>(null);
  let eventError = $state(''), eventsComplete = $state(false);
  let loading = $state(false), error = $state(''), incomplete = $state(false);
  let retry = $state(0);
  let view = $state<'summary' | 'events' | 'logs'>('summary');
  let notice = $state(''), copyAnchor = $state<HTMLButtonElement>();
  let eventsAnchor = $state<HTMLButtonElement>(), logsAnchor = $state<HTMLButtonElement>();
  let revision = 0;
  const current = $derived(details && (details.summary_at ?? 0) > (record.summary_at ?? 0) ? details : record);
  const name = $derived(library.catalog?.games.find(game => game.id === current.game_id)?.name || current.game_name || current.game_id || 'Unknown game');
  const lines = $derived(entries.map(entry => formatLog(entry.message)).filter((entry): entry is LogEntry => entry !== null));
  const stages = $derived(sessionEvents(current, transitions));
  const total = $derived(current.duration_ms == null ? null : current.duration_ms + (!current.ended_at && current.summary_at ? Math.max(0, now - current.summary_at) : 0));
  function date(value?: number | null) { return value && Number.isFinite(value) ? new Date(value).toLocaleString() : 'Not recorded'; }
  $effect(() => {
    const id = record.id; record.summary_at; retry;
    const request = ++revision;
    loading = true; error = '';
    void readLogs(id).then(page => {
      if (request !== revision) return;
      details = page.session; entries = page.entries; cursor = page.next_cursor; incomplete = !page.logs_complete;
      transitions = page.events; eventCursor = page.next_events_cursor ?? null;
      eventError = page.events_error || ''; eventsComplete = !!page.events_complete;
    }).catch(failure => { if (request === revision) { error = String(failure); entries = []; cursor = null; transitions = undefined; eventCursor = null; eventError = 'Stage history needs a retry.'; } })
      .finally(() => { if (request === revision) loading = false; });
    return () => { revision++; };
  });
  async function more(events = false) {
    const next = events ? eventCursor : cursor;
    if (loading || next === null) return;
    await page(events, next, true);
  }
  async function page(events: boolean, next = 0, append = false) {
    if (loading) return;
    const request = revision;
    loading = true;
    if (events) eventError = ''; else error = '';
    try {
      const data = await (events ? readEvents : readLogs)(record.id, next);
      if (request !== revision) return;
      if (data.next_cursor !== null && data.next_cursor <= next) throw new Error('Archive cursor did not advance. Refresh to retry.');
      details = data.session;
      if (events) {
        transitions = append ? [...transitions ?? [], ...data.entries] : data.entries;
        eventCursor = data.next_cursor; eventsComplete = !!data.events_complete;
      } else { entries = append ? [...entries, ...data.entries] : data.entries; cursor = data.next_cursor; }
    } catch (failure) { if (request === revision) { if (events) eventError = String(failure); else error = String(failure); } }
    finally { if (request === revision) loading = false; }
  }
  async function copyId() {
    notice = '';
    try { await copyText(record.id); notice = 'Session ID copied'; } catch (failure) { notice = String(failure); }
  }
  async function copyLogs() { await copySessionLogs(record.id); }
  async function copyEvents() { await copySessionEvents(record.id); }
  function expand(next: 'events' | 'logs') { view = next; }
  async function collapse() {
    const previous = view; view = 'summary'; await tick();
    (previous === 'events' ? eventsAnchor : logsAnchor)?.focus({ preventScroll: true });
  }
</script>

{#snippet archiveFooter(events: boolean)}
  {@const next = events ? eventCursor : cursor}
  {@const failed = events ? eventError : error}
  {#if next !== null}<div class="more"><Button size="small" disabled={loading} onclick={() => void more(events)}>{loading ? 'Loading…' : 'Load more'}</Button></div>{/if}
  {#if !loading && (events ? !eventsComplete : incomplete)}<p class="message">{events ? 'Some older stage transitions were not recorded.' : 'Older output was not recorded.'}</p>{/if}
  {#if failed}<p class="message" role="alert">{failed}</p><Button size="small" onclick={() => events ? void page(true) : next === null ? retry++ : void more()} disabled={loading}>Retry</Button>{/if}
{/snippet}
{#snippet logFooter()}{@render archiveFooter(false)}{/snippet}
{#snippet eventFooter()}{@render archiveFooter(true)}{/snippet}

<DetailsPanel id="session-details" label={`Details for ${name}`} inset>
  <header class="panel-heading">
    <h2>Session details</h2>
    <Button icon size="small" variant="plain" aria-label="Close session details" title="Close session details" onclick={onclose}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg></Button>
  </header>
  {#if view === 'summary'}
    <div class="summary">
      <section class="panel-card info-block" aria-label="Session information">
        <dl>
          <dt>Game</dt><dd title={name}>{name}</dd>
          <dt>Status</dt><dd><SessionStatus record={current} dot={false}/></dd>
          <dt>Start time</dt><dd title={date(current.started_at)}>{date(current.started_at)}</dd>
          <dt>Total time</dt><dd title="Elapsed session time, including startup and shutdown">{duration(total)}</dd>
          <dt>Session ID</dt><dd class="identity"><span title={current.id}>{current.id}</span><div class="id-copy"><Button icon size="small" variant="plain" bind:element={copyAnchor} aria-label="Copy session ID" title="Copy session ID" onclick={() => void copyId()}><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/></svg></Button></div></dd>
        </dl>
      </section>
      <section class="panel-card info-block" aria-labelledby="session-host-heading">
        <h3 id="session-host-heading">Host Details</h3>
        <dl>
          <dt>Provider</dt><dd>Vast.ai</dd>
          <dt>Location</dt><dd class="location" title={current.rig?.geolocation?.replaceAll('_', ' ')}><CountryLabel value={current.rig?.geolocation || ''}/><span>{current.rig?.geolocation?.replaceAll('_', ' ') || 'Not recorded'}</span></dd>
          <dt>GPU</dt><dd title={`${current.rig?.gpu_name?.replaceAll('_', ' ') || 'Not recorded'} · ${amount(current.rig?.gpu_ram ?? null, 'GB', 1024)}`}>{current.rig?.gpu_name?.replaceAll('_', ' ') || 'Not recorded'} · {amount(current.rig?.gpu_ram ?? null, 'GB', 1024)}</dd>
          <dt>CPU</dt><dd title={current.rig?.cpu_name?.replaceAll('_', ' ')}>{current.rig?.cpu_name?.replaceAll('_', ' ') || 'Not recorded'}</dd>
          <dt>Download</dt><dd title={amount(current.rig?.inet_down ?? null, 'Mbps')}>{amount(current.rig?.inet_down ?? null, 'Mbps')}</dd>
          <dt>Upload</dt><dd title={amount(current.rig?.inet_up ?? null, 'Mbps')}>{amount(current.rig?.inet_up ?? null, 'Mbps')}</dd>
        </dl>
      </section>
      <div class="collapsed"><Button full variant="surface" bind:element={eventsAnchor} aria-label="View all session events" aria-expanded="false" onclick={() => expand('events')}><strong>Events</strong><span>View all</span></Button></div>
      <div class="collapsed"><Button full variant="surface" bind:element={logsAnchor} aria-label="View all session logs" aria-expanded="false" onclick={() => expand('logs')}><strong>Logs</strong><span>View all</span></Button></div>
    </div>
  {:else}
    <div class="full">
      {#if view === 'events'}
        <LogOutput lines={stages} label="Session events" copyLabel="Copy all events" emptyText="No stage events were recorded." oncopy={copyEvents} oncollapse={() => void collapse()} trailing={eventFooter}/>
      {:else}
        <LogOutput {lines} label="Full session log" emptyText={loading ? 'Loading logs…' : 'No activity yet.'} oncopy={copyLogs} oncollapse={() => void collapse()} trailing={logFooter}/>
      {/if}
    </div>
  {/if}
  {#if notice}<Notice anchor={copyAnchor} text={notice}/>{/if}
</DetailsPanel>
<style>
  .panel-heading { flex: 0 0 32px; display: flex; align-items: center; justify-content: space-between; gap: var(--page-margin); min-width: 0; }
  h2 { margin: 0; min-width: 0; font-size: 14px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .summary { --field-gap: 8px; --field-height: clamp(14px, calc((100cqh - 32px - var(--button-size) * 2 - var(--page-margin) * 9 - 16px - var(--field-gap) * 9) / 11), 22px); display: flex; flex-direction: column; gap: var(--page-margin); min-height: 0; }
  .info-block { flex: 0 0 auto; }
  h3 { margin: 0 0 var(--page-margin); font-size: 12px; font-weight: 600; line-height: 16px; }
  dl { margin: 0; display: grid; grid-template-columns: minmax(56px, 28%) minmax(0, 1fr); grid-auto-rows: var(--field-height); align-items: center; gap: var(--field-gap) var(--page-margin); font-size: 11px; line-height: 1.2; }
  dt, dd { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  dt { color: var(--text-muted); }
  dd { margin: 0; }
  .identity { position: relative; overflow: visible; }
  .identity > span { display: block; padding-right: 32px; overflow: hidden; text-overflow: ellipsis; color: var(--log-info); }
  .id-copy { position: absolute; right: 0; top: calc((100% - 32px) / 2); }
  .location { display: flex; align-items: center; gap: 8px; }
  .location > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .collapsed { flex: 0 0 var(--button-size); min-width: 0; }
  .collapsed :global(.face) { justify-content: space-between; padding-inline: var(--page-margin); }
  .collapsed strong, .collapsed span { font-size: 12px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .collapsed span { color: var(--text-muted); }
  .full { flex: 1; min-height: 0; }
  .more { display: flex; justify-content: center; margin-top: 8px; }
  .message { margin: 8px 0 0; color: var(--text-muted); font: 11px/1.5 ui-monospace, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
  @container (max-height: 500px) { .summary { --field-gap: 4px; } }
  @container (max-height: 400px) { .summary { --field-gap: 0px; } }
</style>
