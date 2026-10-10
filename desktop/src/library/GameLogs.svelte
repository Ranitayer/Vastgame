<script lang="ts">
  import Button from '../components/Button.svelte';
  import LogOutput from '../components/LogOutput.svelte';
  import type { LogEntry } from '../session/logs';
  let { open = $bindable(false), lines }: { open?: boolean; lines: LogEntry[] } = $props();
  let toggle = $state<HTMLButtonElement>();
  function collapse() { open = false; toggle?.focus({ preventScroll: true }); }
</script>
<div class="logs">
  {#if open}<div class="output" id="game-launch-log"><LogOutput {lines} follow oncollapse={collapse}/></div>{/if}
  <div class="toggle"><Button variant="plain" bind:element={toggle} aria-expanded={open} aria-controls={open ? 'game-launch-log' : undefined} onclick={() => open = !open}>Logs</Button></div>
</div>
<style>
  .logs { display: grid; height: 100%; min-height: 0; grid-template-rows: minmax(0, 1fr) var(--button-size); gap: var(--page-margin); }
  .toggle { grid-row: 2; display: flex; align-items: center; gap: var(--page-margin); min-width: 0; }
  .output { grid-row: 1; min-height: 0; width: 100%; }
</style>
