<script lang="ts">
  import Button from '../components/Button.svelte';
  let { open = $bindable(false), lines }: { open?: boolean; lines: string[] } = $props();
  let output: HTMLDivElement;
  let following = $state(true);
  $effect(() => { lines; open; if (output && following) requestAnimationFrame(() => { if (output) output.scrollTop = output.scrollHeight; }); });
</script>
<div class="logs">
  {#if open}<div id="game-launch-log" class="output" bind:this={output} onscroll={() => following = output.scrollHeight - output.scrollTop - output.clientHeight < 32} role="log" aria-label="Game launch logs" tabindex="0"><pre>{lines.length ? lines.join('\n') : 'No launch activity yet.'}</pre></div>{/if}
  <div class="toggle"><Button variant="plain" aria-expanded={open} aria-controls={open ? 'game-launch-log' : undefined} onclick={() => open = !open}>Logs</Button></div>
</div>
<style>
  .logs { display: grid; height: 100%; min-height: 0; grid-template-rows: minmax(0, 1fr) var(--button-size); gap: var(--page-margin); }
  .toggle { grid-row: 2; display: flex; align-items: center; gap: var(--page-margin); min-width: 0; }
  .output { grid-row: 1; min-height: 0; width: 100%; padding: var(--page-margin); border-radius: 16px; background: var(--surface); overflow-y: auto; scrollbar-width: thin; scrollbar-color: var(--surface-active) transparent; }
  pre { white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; color: var(--text-muted); font: 11px/1.5 ui-monospace, monospace; }
</style>
