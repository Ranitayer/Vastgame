<script lang="ts">
  import { price } from './types';
  let { limit = $bindable<number | null>(null), ceiling, disabled = false }: { limit?: number | null; ceiling: number; disabled?: boolean } = $props();
</script>
<label class="price-limit"><span>{limit === null || limit >= ceiling ? 'Any price' : `${price(limit)} / hr max`}</span><input type="range" {disabled} aria-label="Maximum hourly price in US dollars" aria-valuetext={limit === null || limit >= ceiling ? 'Any price' : `${price(limit)} per hour maximum`} min="0" max={ceiling} step="0.01" value={limit ?? ceiling} oninput={(event) => limit = Number(event.currentTarget.value)} /></label>
<style>
  .price-limit { width: 100%; min-width: 0; display: grid; gap: 6px; color: var(--text-muted); font-size: 12px; }
  .price-limit span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  input[type='range'] { appearance: none; width: 100%; height: 20px; margin: 0; background: transparent; cursor: pointer; }
  input[type='range']::-webkit-slider-runnable-track { height: 5px; border-radius: 8px; background: var(--surface-active); }
  input[type='range']::-webkit-slider-thumb { appearance: none; width: 16px; height: 16px; margin-top: -5.5px; border: 0; border-radius: 50%; background: var(--text-muted); }
  input[type='range']::-moz-range-track { height: 5px; border-radius: 8px; background: var(--surface-active); }
  input[type='range']::-moz-range-thumb { width: 16px; height: 16px; border: 0; border-radius: 50%; background: var(--text-muted); }
  input[type='range']:focus-visible { outline: 2px solid var(--focus); outline-offset: 3px; border-radius: 8px; }
</style>
