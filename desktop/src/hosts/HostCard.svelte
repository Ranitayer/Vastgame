<script lang="ts">
  import { amount, gpuName, location, price, type Host } from './types';
  import CountryLabel from './CountryLabel.svelte';
  let { host, selected, onclick }: { host: Host; selected: boolean; onclick: () => void } = $props();
</script>

<button class="card" class:selected onclick={onclick} aria-label={`View ${gpuName(host)} in ${location(host)}, ${price(host.dph_total)} per hour`} aria-expanded={selected} aria-controls="host-details">
  <div class="card-header">
    <span class="gpu-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24"><rect x="5" y="5" width="14" height="14" rx="3"/><path d="M9 9h6v6H9z M9 2v3m6-3v3M9 19v3m6-3v3M2 9h3m-3 6h3m14-6h3m-3 6h3"/></svg>
    </span>
    <div class="hardware">
      <div class="gpu-title"><strong title={gpuName(host)}>{gpuName(host)}</strong><span class="vram">{amount(host.gpu_ram, 'GB', 1024)}</span></div>
      <span>{amount(host.cpu_cores_effective, 'vCPU')} · {amount(host.cpu_ram, 'GB RAM', 1024)}</span>
    </div>
    <span class="open" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M5 12h14m-5-5 5 5-5 5"/></svg></span>
  </div>
  <div class="card-footer"><span class="country"><CountryLabel value={host.geolocation}/></span><span class="price">{price(host.dph_total)}<small> / hr</small></span></div>
</button>

<style>
  .card { width: 100%; height: auto; min-height: 136px; display: flex; flex-direction: column; justify-content: space-between; gap: 20px; padding: 20px; border-radius: 24px; background: var(--surface-hover); text-align: left; font: inherit; cursor: pointer; color: var(--text); }
  .card:hover { background: var(--surface-active); }
  .card.selected { box-shadow: inset 0 0 0 2px var(--accent); }
  .card-header { display: flex; align-items: center; gap: 12px; min-width: 0; width: 100%; }
  .gpu-icon { width: 42px; height: 42px; display: grid; place-items: center; flex-shrink: 0; border-radius: 14px; background: var(--surface); color: var(--text-muted); }
  .gpu-icon svg { width: 24px; height: 24px; }
  .hardware { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 7px; }
  .gpu-title { display: flex; align-items: baseline; min-width: 0; gap: 8px; }
  .gpu-title .vram { font-size: 12px; color: var(--text-muted); white-space: nowrap; flex-shrink: 0; }
  strong { min-width: 0; font-size: 16px; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .hardware span { font-size: 12px; color: var(--text-muted); line-height: 1.5; }
  .open { display: grid; place-items: center; width: 32px; height: 32px; flex-shrink: 0; border-radius: 50%; background: var(--surface); color: var(--text-muted); }
  .card-footer { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; width: 100%; }
  .country { font-size: 13px; color: var(--text-muted); overflow-wrap: anywhere; }
  .price { white-space: nowrap; font-size: 17px; font-weight: 600; }
  small { font-size: 12px; font-weight: 400; color: var(--text-muted); }
</style>
