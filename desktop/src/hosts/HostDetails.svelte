<script lang="ts">
  import CountryLabel from './CountryLabel.svelte';
  import DetailIcon from './DetailIcon.svelte';
  import { amount, gpuName, price, type Host } from './types';
  let { host, onclose }: { host: Host; onclose: () => void } = $props();
  const fees = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 6 });
  const cost = (value: number | null) => value === null ? 'Not reported' : `${fees.format(value)} / GB`;
</script>

<aside class="details" aria-labelledby="host-details-title">
  <header>
    <span class="gpu-icon"><DetailIcon kind="gpu"/></span>
    <div class="identity"><h2 id="host-details-title">{gpuName(host)}</h2><p>{amount(host.gpu_ram, 'GB VRAM', 1024)}</p></div>
    <button class="close" aria-label="Close host details" onclick={onclose}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg></button>
  </header>
  <div class="summary"><CountryLabel value={host.geolocation}/><strong>{price(host.dph_total)}<small> / hr</small></strong></div>
  <dl class="specs">
    <div class="spec processor"><dt><DetailIcon kind="cpu"/>Processor</dt><dd title={host.cpu_name}>{host.cpu_name || 'Not reported'}<small>{amount(host.cpu_cores_effective, 'vCPUs')} · {amount(host.cpu_ghz, 'GHz')}</small></dd></div>
    <div class="spec memory"><dt><DetailIcon kind="memory"/>Memory</dt><dd>{amount(host.cpu_ram, 'GB RAM', 1024)}</dd></div>
    <div class="spec"><dt><DetailIcon kind="storage"/>Storage</dt><dd>{amount(host.disk_space, 'GB')}<small title={host.disk_name}>{host.disk_name || 'Disk type not reported'}</small><small>{amount(host.disk_bw, 'MB/s')} read</small></dd></div>
    <div class="spec"><dt><DetailIcon kind="download"/>Download</dt><dd>{amount(host.inet_down, 'Mbps')}<small>{cost(host.inet_down_cost)}</small></dd></div>
    <div class="spec"><dt><DetailIcon kind="upload"/>Upload</dt><dd>{amount(host.inet_up, 'Mbps')}<small>{cost(host.inet_up_cost)}</small></dd></div>
  </dl>
</aside>

<style>
  .details { height: 100%; min-width: 0; min-height: 0; padding: 20px; border-radius: 24px; background: var(--surface-hover); display: flex; flex-direction: column; gap: 16px; }
  header { display: flex; align-items: center; gap: 12px; }
  .gpu-icon { display: grid; place-items: center; width: 42px; height: 42px; flex-shrink: 0; border-radius: 14px; background: var(--surface); color: var(--text-muted); }
  .identity { flex: 1; min-width: 0; }
  h2 { margin: 0; font-size: 20px; font-weight: 600; overflow-wrap: anywhere; }
  .identity p { margin: 5px 0 0; font-size: 12px; color: var(--text-muted); }
  .close { width: 28px; height: 28px; flex-shrink: 0; border-radius: 10px; background: var(--surface); }
  .summary { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; font-size: 12px; color: var(--text-muted); }
  .summary strong { font-size: 19px; color: var(--text); font-weight: 600; }
  .summary small { display: inline; font-weight: 400; }
  .specs { margin: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; align-items: start; }
  .spec { min-width: 0; width: 100%; padding: 12px; border-radius: 18px; background: var(--surface); text-align: center; }
  .processor { grid-column: 1 / -1; }
  .memory { align-self: stretch; }
  dt { display: flex; align-items: center; justify-content: center; gap: 8px; color: var(--text-muted); font-size: 12px; }
  dd { margin: 6px 0 0; font-size: 15px; line-height: 1.4; overflow-wrap: anywhere; }
  small { display: block; margin-top: 3px; font-size: 11px; color: var(--text-muted); }
  .spec small { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
  :global(.details svg) { width: 18px; height: 18px; flex-shrink: 0; }
  @media (max-height: 700px), (max-width: 760px) {
    .details { padding: 12px; gap: 10px; }
    header { gap: 8px; }
    h2 { font-size: 16px; }
    .gpu-icon { width: 32px; height: 32px; border-radius: 10px; }
    .summary strong { font-size: 16px; }
    .specs { gap: 8px; }
    .spec { padding: 10px; border-radius: 14px; }
    dt { gap: 5px; font-size: 11px; }
    dd { margin-top: 6px; font-size: 12px; }
    small { font-size: 10px; }
  }
  @media (max-height: 650px) {
    .details { gap: 8px; }
    .spec { padding: 8px; }
    .specs { gap: 6px; }
    .processor dd { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
    .spec :global(svg) { width: 14px; height: 14px; }
    dd { margin-top: 4px; }
  }
</style>
