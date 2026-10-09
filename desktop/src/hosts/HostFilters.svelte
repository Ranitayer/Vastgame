<script lang="ts">
  import { price } from './types';
  import Dropdown from '../components/Dropdown.svelte';
  let { search = $bindable(''), continent = $bindable(''), sort = $bindable(''), limit = $bindable<number | null>(null), continents, ceiling, loading, onrefresh }: {
    search?: string; continent?: string; sort?: string; limit?: number | null;
    continents: string[]; ceiling: number; loading: boolean; onrefresh: () => void;
  } = $props();
</script>

<div class="filters">
  <div class="search-group">
    <label class="search"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/></svg><input type="search" placeholder="Find a GPU or CPU" aria-label="Search hosts" bind:value={search}/></label>
    <button class="refresh" disabled={loading} aria-label={loading ? 'Refreshing hosts' : 'Refresh hosts'} title="Refresh hosts" onclick={onrefresh}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5 M20 12a8 8 0 1 0-2 5 M20 7v5"/></svg></button>
  </div>
  <Dropdown bind:value={continent} options={continents} label="Continent" placeholder="All continents"/>
  <div class="price-sort">
    <Dropdown bind:value={sort} options={['Highest price', 'Best value']} label="Sort hosts" placeholder="Lowest price"/>
    <label class="price-limit"><span>{limit === null || limit >= ceiling ? 'Any price' : `${price(limit)} / hr max`}</span><input type="range" aria-label="Maximum hourly price in US dollars" aria-valuetext={limit === null || limit >= ceiling ? 'Any price' : `${price(limit)} per hour maximum`} min="0" max={ceiling} step="0.01" value={limit ?? ceiling} oninput={(event) => limit = Number(event.currentTarget.value)} /></label>
  </div>
</div>

<style>
  .filters { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
  .search-group { display: flex; flex: 0 1 292px; min-width: 0; gap: 8px; }
  .search { display: flex; flex: 0 1 240px; width: 240px; min-width: 0; align-items: center; gap: 12px; padding: 0 16px; height: 44px; border-radius: 16px; background: var(--surface-hover); color: var(--text-muted); }
  .search:focus-within { outline: 2px solid var(--focus); outline-offset: -2px; }
  input[type='search'] { width: 100%; min-width: 0; padding: 0; border: 0; outline: none; font: inherit; font-size: 13px; color: var(--text); background: transparent; }
  input::placeholder { color: var(--text-muted); }
  .refresh { flex-shrink: 0; width: 44px; height: 44px; border-radius: 16px; background: var(--surface-hover); }
  .refresh:hover { background: var(--surface-active); }
  .refresh:disabled { opacity: 0.5; }
  .price-sort { display: flex; flex: 0 0 auto; flex-wrap: nowrap; align-items: center; gap: 12px; }
  .price-limit { flex: 0 0 180px; width: 180px; min-width: 0; display: grid; gap: 6px; color: var(--text-muted); font-size: 12px; }
  input[type='range'] { appearance: none; width: 100%; height: 20px; margin: 0; background: transparent; cursor: pointer; }
  input[type='range']::-webkit-slider-runnable-track { height: 5px; border-radius: 8px; background: var(--surface-active); }
  input[type='range']::-webkit-slider-thumb { appearance: none; width: 16px; height: 16px; margin-top: -5.5px; border: 0; border-radius: 50%; background: var(--text-muted); }
  input[type='range']::-moz-range-track { height: 5px; border-radius: 8px; background: var(--surface-active); }
  input[type='range']::-moz-range-thumb { width: 16px; height: 16px; border: 0; border-radius: 50%; background: var(--text-muted); }
  input[type='range']:focus-visible { outline: 2px solid var(--focus); outline-offset: 3px; border-radius: 8px; }
</style>
