<script lang="ts">
  import Button from '../components/Button.svelte';
  import type { LogEntry } from '../session/logs';
  let { open = $bindable(false), lines }: { open?: boolean; lines: LogEntry[] } = $props();
  let output: HTMLDivElement;
  let following = $state(true);
  const clock = new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
  $effect(() => { lines; open; if (output && following) requestAnimationFrame(() => { if (output) output.scrollTop = output.scrollHeight; }); });
</script>
<div class="logs">
  {#if open}<div id="game-launch-log" class="output" bind:this={output} onscroll={() => following = output.scrollHeight - output.scrollTop - output.clientHeight < 32} role="log" aria-label="Important rig activity" tabindex="0">
    <header><strong>Activity</strong><span>{lines.length} events</span></header>
    {#if !lines.length}<p class="empty">No activity yet.</p>{/if}
    {#each lines as entry}
      <div class="entry" data-level={entry.level}>
        <time datetime={new Date(entry.time).toISOString()} title="Event time">{clock.format(entry.time)}</time>
        <div class="event"><span class="tag">{entry.level === 'success' ? 'OK' : entry.level.toUpperCase()}</span><span class="scope">{entry.scope}</span><span class="message">{entry.message}</span></div>
      </div>
    {/each}
  </div>{/if}
  <div class="toggle"><Button variant="plain" aria-expanded={open} aria-controls={open ? 'game-launch-log' : undefined} onclick={() => open = !open}>Logs</Button></div>
</div>
<style>
  .logs { display: grid; height: 100%; min-height: 0; grid-template-rows: minmax(0, 1fr) var(--button-size); gap: var(--page-margin); }
  .toggle { grid-row: 2; display: flex; align-items: center; gap: var(--page-margin); min-width: 0; }
  .output { grid-row: 1; min-height: 0; width: 100%; padding: var(--page-margin); border-radius: 16px; background: var(--surface); overflow-y: auto; scrollbar-width: thin; scrollbar-color: var(--surface-active) transparent; }
  header { display: flex; align-items: center; justify-content: space-between; gap: var(--page-margin); margin-bottom: var(--page-margin); font-size: 12px; }
  header span, time, .scope, .empty { color: var(--text-muted); }
  .entry { --event-color: var(--log-info); display: grid; grid-template-columns: 58px minmax(0, 1fr); gap: 10px; padding-block: 6px; font: 11px/1.5 ui-monospace, monospace; }
  .entry[data-level='success'] { --event-color: var(--log-success); }
  .entry[data-level='warning'] { --event-color: var(--log-warning); }
  .entry[data-level='error'] { --event-color: var(--log-error); }
  time { font-variant-numeric: tabular-nums; font-size: 10px; padding-top: 1px; }
  .event { min-width: 0; }
  .tag { color: var(--event-color); font-size: 9px; font-weight: 700; margin-right: 6px; }
  .scope { font-size: 9px; }
  .message { display: block; color: var(--text); overflow-wrap: anywhere; }
  .entry[data-level='error'] .message, .entry[data-level='warning'] .message { color: var(--event-color); }
  .empty { margin: 0; font: 11px/1.5 ui-monospace, monospace; }
</style>
