<script lang="ts">
  import Button from './Button.svelte';
  let { value = $bindable(0), label, max, step = 1, unit = '', disabled = false }: { value?: number; label: string; max: number; step?: number; unit?: string; disabled?: boolean } = $props();
  function change(direction: number) { value = Math.max(0, Math.min(max, Number(((value || 0) + step * direction).toFixed(6)))); }
</script>
<div class="number-field">
  <input type="number" min="0" {max} {step} {disabled} aria-label={label} bind:value/>
  {#if unit}<span>{unit}</span>{/if}
  <div class="arrows">
    <Button icon size="small" variant="plain" disabled={disabled || value >= max} aria-label={`Increase ${label.toLowerCase()}`} onclick={() => change(1)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 14 5-5 5 5"/></svg></Button>
    <Button icon size="small" variant="plain" disabled={disabled || value <= 0} aria-label={`Decrease ${label.toLowerCase()}`} onclick={() => change(-1)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg></Button>
  </div>
</div>
<style>
  .number-field { display: flex; align-items: center; gap: 8px; background: var(--surface); border-radius: 99px; min-width: 0; height: var(--button-size); padding-left: 14px; }
  input { flex: 1; width: 0; min-width: 0; border: 0; background: transparent; color: var(--text); font: inherit; font-size: 12px; appearance: textfield; }
  input::-webkit-inner-spin-button, input::-webkit-outer-spin-button { appearance: none; margin: 0; }
  input:focus-visible { outline: 2px solid var(--focus); border-radius: 4px; }
  span { font-size: 11px; color: var(--text-muted); }
  .arrows { display: flex; padding-right: 4px; }
</style>
