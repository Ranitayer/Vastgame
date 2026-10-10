<script lang="ts">
  import Button from './Button.svelte';
  let { checked = $bindable(false), label, disabled = false }: { checked?: boolean; label: string; disabled?: boolean } = $props();
</script>
<div class="toggle"><Button {disabled} role="switch" aria-checked={checked} aria-label={label} onclick={() => checked = !checked}><span class="track" class:on={checked}><span class="thumb"></span></span></Button></div>
<style>
  .toggle { display: flex; justify-content: flex-end; }
  .track { display: flex; align-items: center; width: 34px; height: 20px; border-radius: 99px; background: var(--surface-active); padding: 3px; }
  .track.on { background: var(--accent); }
  .thumb { width: 14px; height: 14px; border-radius: 50%; background: var(--text); }
  .on { justify-content: flex-end; }
</style>
