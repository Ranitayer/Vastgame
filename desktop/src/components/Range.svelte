<script lang="ts">
  let { value = $bindable(0), min = 0, max, step = 1, label, text, disabled = false }: { value?: number; min?: number; max: number; step?: number; label: string; text: string; disabled?: boolean } = $props();
</script>
<label class="range"><span>{text}</span><input type="range" {min} {max} {step} {disabled} aria-label={label} aria-valuetext={text} bind:value/></label>
<style>
  .range { width: 100%; min-width: 0; display: grid; gap: 6px; color: var(--text-muted); font-size: 12px; }
  .range span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  input { appearance: none; width: 100%; height: 20px; margin: 0; background: transparent; cursor: pointer; }
  input::-webkit-slider-runnable-track { height: 5px; border-radius: 8px; background: var(--surface-active); }
  input::-webkit-slider-thumb { appearance: none; width: 16px; height: 16px; margin-top: -5.5px; border: 0; border-radius: 50%; background: var(--text-muted); }
  input::-moz-range-track { height: 5px; border-radius: 8px; background: var(--surface-active); }
  input::-moz-range-thumb { width: 16px; height: 16px; border: 0; border-radius: 50%; background: var(--text-muted); }
  input:focus-visible { outline: 2px solid var(--focus); outline-offset: 3px; border-radius: 8px; }
  input:disabled { cursor: default; opacity: 0.5; }
</style>
