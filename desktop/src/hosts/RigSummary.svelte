<script lang="ts">
  import CountryLabel from './CountryLabel.svelte';
  import { amount, gpuName, price, type Host } from './types';
  let { host, download = false, large = false, disk = true, highlightPrice = false }: { host: Host; download?: boolean; large?: boolean; disk?: boolean; highlightPrice?: boolean } = $props();
</script>
<span class="summary" class:large>
  <CountryLabel value={host.geolocation}/><span class="separator">–</span><span class="gpu" title={gpuName(host)}>{gpuName(host)}</span><span class="separator vram">–</span><span class="vram" title="VRAM">{amount(host.gpu_ram, 'GB', 1024)}</span>
  {#if download}<span class="separator download">–</span><span class="download" title="Download speed">{amount(host.inet_down, 'Mbps')}</span>{/if}
  {#if disk}<span class="separator">–</span><span title="Disk space">{amount(host.disk_space, 'GB')}</span>{/if}<span class="separator">–</span><span class:highlight={highlightPrice} title="Hourly price">{price(host.dph_total)}/h</span>
</span>
<style>
  .summary { display: flex; align-items: center; gap: 5px; width: 100%; min-width: 0; }
  .summary > span { font-size: 11px; white-space: nowrap; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .separator { flex-shrink: 0; color: var(--text-muted); }
  .gpu { flex: 0 1 auto; }
  .summary.large > span { font-size: 13px; }
  .summary.large { justify-content: center; }
  .summary :global(.country-label) { flex-shrink: 0; }
  .summary > .highlight { color: var(--price); font-weight: 700; flex-shrink: 0; }
  @container host-pill-info (min-width: 0px) {
    .summary > .vram, .summary > .download { flex-shrink: 0; }
  }
  @container host-pill-info (max-width: 340px) {
    .summary > .download { display: none; }
  }
  @container host-pill-info (max-width: 250px) {
    .summary > .vram { display: none; }
  }
</style>
