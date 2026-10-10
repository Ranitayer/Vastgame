<script lang="ts">
  import { onDestroy, onMount, type Snippet } from 'svelte';
  import { copyText } from './clipboard';
  import Button from './Button.svelte';
  import type { LogEntry } from '../session/logs';
  let { lines, label = 'Full rig output', copyLabel = 'Copy all logs', emptyText = 'No activity yet.', oncopy, oncollapse, trailing, follow = false }: { lines: LogEntry[]; label?: string; copyLabel?: string; emptyText?: string; oncopy?: () => Promise<void>; oncollapse?: () => void; trailing?: Snippet; follow?: boolean } = $props();
  let output: HTMLDivElement;
  let following = $state(false);
  let copying = $state(false);
  let copied = $state(false);
  let copyError = $state('');
  let copyTimer: ReturnType<typeof setTimeout> | undefined;
  onDestroy(() => clearTimeout(copyTimer));
  onMount(() => { following = follow; output?.focus({ preventScroll: true }); });
  async function copyLogs() {
    if (copying) return;
    copying = true;
    const text = lines.map(entry => entry.message).join('\n');
    copyError = '';
    try {
      if (oncopy) await oncopy(); else await copyText(text);
      copied = true;
      clearTimeout(copyTimer);
      copyTimer = setTimeout(() => copied = false, 1000);
    } catch (error) { copyError = String(error); }
    finally { copying = false; }
  }
  $effect(() => { lines; if (output && following) requestAnimationFrame(() => { if (output) output.scrollTop = output.scrollHeight; }); });
</script>
<div class="output">
    <span class="feedback" role="status">{copyError || (copied ? 'Copied' : '')}</span>
    <div class="entries" bind:this={output} onscroll={() => following = output.scrollHeight - output.scrollTop - output.clientHeight < 32} onkeydown={(event) => { if (event.key === 'Escape' && oncollapse) { event.preventDefault(); event.stopPropagation(); oncollapse(); } }} role="log" aria-label={label} tabindex="0">
    <div class="actions" class:copied>
      {#if oncollapse}<div class="collapse-button"><Button icon size="small" variant="tonal" aria-label="Collapse view" title="Collapse view" onclick={oncollapse}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h5V4M20 9h-5V4M4 15h5v5M20 15h-5v5"/></svg></Button></div>{/if}
      <div class="copy-button"><Button icon size="small" variant="tonal" aria-label={copied ? 'Copied' : copying ? 'Copying' : copyLabel} title={copyError || copyLabel} disabled={copying || !lines.length} onclick={() => void copyLogs()}><span class="copy-content"><span class="copy-label" aria-hidden="true">Copied</span><span class="copy-glyph"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/></svg></span></span></Button></div>
    </div>
    {#if !lines.length}<p class="empty">{emptyText}</p>{/if}
    {#each lines as entry}
      <div class="entry" data-level={entry.level}>{entry.message}</div>
    {/each}
    {#if trailing}{@render trailing()}{/if}
    </div>
    {#if copyError}<p class="copy-error" role="alert">{copyError}</p>{/if}
  </div>
<style>
  .output { position: relative; height: 100%; min-height: 0; width: 100%; padding: 8px; border-radius: 16px; background: var(--surface); display: grid; grid-template-rows: minmax(0, 1fr); container-type: inline-size; }
  .empty { color: var(--text-muted); }
  .entries { grid-column: 1; grid-row: 1; min-height: 0; height: 100%; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: none; }
  .entries::-webkit-scrollbar { display: none; }
  .entries:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; border-radius: 8px; }
  .entry { --event-color: var(--log-info); padding-block: 2px; font: 11px/1.5 ui-monospace, monospace; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--event-color); }
  .entry[data-level='success'] { --event-color: var(--log-success); }
  .entry[data-level='warning'] { --event-color: var(--log-warning); }
  .entry[data-level='error'] { --event-color: var(--log-error); }
  .empty { margin: 0; font: 11px/1.5 ui-monospace, monospace; }
  .actions { position: sticky; top: 0; z-index: 1; float: right; display: flex; align-items: center; gap: 8px; height: 32px; margin: 0 0 4px 8px; }
  .copy-button { position: relative; width: 32px; height: 32px; }
  .copy-button :global(.control) { position: absolute; right: 0; top: 0; width: 32px; transition: width var(--button-duration) ease-out; }
  .copied .copy-button { width: 88px; }
  .copied .copy-button :global(.control) { width: 88px; }
  .copy-button :global(.face) { overflow: hidden; }
  .copy-content { display: flex; align-items: center; color: var(--text); }
  .copy-label { width: 0; overflow: hidden; opacity: 0; transition: width var(--button-duration) ease-out, opacity var(--button-duration) ease-out; white-space: nowrap; text-align: center; }
  .copied .copy-label { width: 56px; opacity: 1; }
  .copy-glyph { display: grid; place-items: center; width: 32px; height: 32px; flex-shrink: 0; }
  .copy-glyph svg { width: 16px; height: 16px; }
  .feedback { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }
  @container (max-width: 180px) { .actions { gap: 4px; margin-left: 4px; } .copied .copy-label { width: 40px; } .copied .copy-button, .copied .copy-button :global(.control) { width: 72px; } }
  @media (prefers-reduced-motion: reduce) { .copy-button :global(.control), .copy-label { transition: none; } }
  .copy-error { position: absolute; bottom: 8px; left: 8px; right: 8px; margin: 0; padding: 8px; border-radius: 8px; background: var(--surface-hover); color: var(--log-error); font-size: 11px; }
</style>
