<script lang="ts">
  import { onDestroy } from 'svelte';
  import Button from '../components/Button.svelte';
  import type { LogEntry } from '../session/logs';
  let { open = $bindable(false), lines }: { open?: boolean; lines: LogEntry[] } = $props();
  let output: HTMLDivElement;
  let following = $state(true);
  let copied = $state(false);
  let copyError = $state('');
  let copyTimer: ReturnType<typeof setTimeout> | undefined;
  onDestroy(() => clearTimeout(copyTimer));
  async function copyLogs() {
    const text = lines.map(entry => entry.message).join('\n');
    copyError = '';
    try {
      try {
        await navigator.clipboard.writeText(text);
      } catch {
        // Older Linux webviews lack the async clipboard API; keep the same button.
        const previous = document.activeElement as HTMLElement | null;
        const field = document.createElement('textarea');
        field.value = text;
        field.style.cssText = 'position:fixed;left:-9999px;top:0';
        document.body.append(field);
        try { field.focus({ preventScroll: true }); field.select(); if (!document.execCommand('copy')) throw new Error('Copy failed'); }
        finally { field.remove(); previous?.focus({ preventScroll: true }); }
      }
      copied = true;
      clearTimeout(copyTimer);
      copyTimer = setTimeout(() => copied = false, 1000);
    } catch { copyError = 'Could not copy logs. Select the text and copy manually.'; }
  }
  $effect(() => { lines; open; if (output && following) requestAnimationFrame(() => { if (output) output.scrollTop = output.scrollHeight; }); });
</script>
<div class="logs">
  {#if open}<div class="output">
    <span class="feedback" role="status">{copyError || (copied ? 'Logs copied' : '')}</span>
    <div id="game-launch-log" class="entries" bind:this={output} onscroll={() => following = output.scrollHeight - output.scrollTop - output.clientHeight < 32} role="log" aria-label="Full rig output" tabindex="0">
    <div class="copy-button" class:copied><Button icon size="small" variant="tonal" aria-label={copied ? 'Logs copied' : 'Copy all logs'} title={copyError || 'Copy all logs'} disabled={!lines.length} onclick={() => void copyLogs()}><span class="copy-content"><span class="copy-label" aria-hidden="true">Copied</span><span class="copy-glyph"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/></svg></span></span></Button></div>
    {#if !lines.length}<p class="empty">No activity yet.</p>{/if}
    {#each lines as entry}
      <div class="entry" data-level={entry.level}>{entry.message}</div>
    {/each}
    </div>
  </div>{/if}
  <div class="toggle"><Button variant="plain" aria-expanded={open} aria-controls={open ? 'game-launch-log' : undefined} onclick={() => open = !open}>Logs</Button></div>
</div>
<style>
  .logs { display: grid; height: 100%; min-height: 0; grid-template-rows: minmax(0, 1fr) var(--button-size); gap: var(--page-margin); }
  .toggle { grid-row: 2; display: flex; align-items: center; gap: var(--page-margin); min-width: 0; }
  .output { position: relative; grid-row: 1; min-height: 0; width: 100%; padding: 8px; border-radius: 16px; background: var(--surface); display: grid; grid-template-rows: minmax(0, 1fr); }
  .empty { color: var(--text-muted); }
  .entries { grid-column: 1; grid-row: 1; min-height: 0; height: 100%; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; scrollbar-color: var(--surface-active) transparent; }
  .entry { --event-color: var(--log-info); padding-block: 2px; font: 11px/1.5 ui-monospace, monospace; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--event-color); }
  .entry[data-level='success'] { --event-color: var(--log-success); }
  .entry[data-level='warning'] { --event-color: var(--log-warning); }
  .entry[data-level='error'] { --event-color: var(--log-error); }
  .empty { margin: 0; font: 11px/1.5 ui-monospace, monospace; }
  .copy-button { position: relative; float: right; width: 32px; height: 32px; margin: 0 0 4px 8px; }
  .copy-button :global(.control) { position: absolute; right: 0; top: 0; width: 32px; transition: width var(--button-duration) ease-out; }
  .copy-button.copied { width: 88px; }
  .copy-button.copied :global(.control) { width: 88px; }
  .copy-button :global(.face) { overflow: hidden; }
  .copy-content { display: flex; align-items: center; color: var(--text); }
  .copy-label { width: 0; overflow: hidden; opacity: 0; transition: width var(--button-duration) ease-out, opacity var(--button-duration) ease-out; white-space: nowrap; text-align: center; }
  .copied .copy-label { width: 56px; opacity: 1; }
  .copy-glyph { display: grid; place-items: center; width: 32px; height: 32px; flex-shrink: 0; }
  .copy-glyph svg { width: 16px; height: 16px; }
  .feedback { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  @media (prefers-reduced-motion: reduce) { .copy-button :global(.control), .copy-label { transition: none; } }
</style>
