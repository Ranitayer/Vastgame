<script lang="ts">
  import DetailIcon from './DetailIcon.svelte';
  import { amount, type Host } from './types';
  let { host }: { host: Host } = $props();
</script>
  <dl class="specs">
    <div class="spec"><dt><DetailIcon kind="cpu"/>Processor</dt><dd title={host.cpu_name}>{host.cpu_name || 'Not reported'}<small>{amount(host.cpu_cores_effective, 'vCPUs')} · {amount(host.cpu_ghz, 'GHz')}</small></dd></div>
    <div class="spec"><dt><DetailIcon kind="memory"/>Memory</dt><dd>{amount(host.cpu_ram, 'GB RAM', 1024)}</dd></div>
    <div class="spec"><dt><DetailIcon kind="download"/>Download</dt><dd>{amount(host.inet_down, 'Mbps')}</dd></div>
    <div class="spec"><dt><DetailIcon kind="upload"/>Upload</dt><dd>{amount(host.inet_up, 'Mbps')}</dd></div>
  </dl>
<style>
  .specs { margin: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--page-margin); align-items: start; }
  .spec { min-width: 0; width: 100%; padding: var(--page-margin); border-radius: 14px; background: var(--surface); text-align: center; align-self: stretch; display: flex; flex-direction: column; justify-content: center; }
  dt { display: flex; align-items: center; justify-content: center; gap: 5px; color: var(--text-muted); font-size: 10px; }
  dd { margin: 6px 0 0; font-size: 12px; line-height: 1.4; overflow-wrap: anywhere; }
  small { display: block; margin-top: 3px; font-size: 10px; color: var(--text-muted); }
  .spec small { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }

  .specs :global(svg) { width: 14px; height: 14px; }
  @media (max-height: 650px) {
    dd { margin-top: 4px; }
  }
</style>
