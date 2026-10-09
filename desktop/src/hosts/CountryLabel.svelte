<script module lang="ts">
  const flags = import.meta.glob<string>('./flags/*.svg', { eager: true, query: '?url', import: 'default' });
</script>

<script lang="ts">
  import { countryCode } from './types';
  let { value }: { value: string } = $props();
  const source = $derived(flags[`./flags/${countryCode(value)}.svg`]);
</script>

<span class="country-label">
  {#if source}<img src={source} width="20" height="14" alt="" loading="lazy" decoding="async" />{/if}
  <span>{value.replaceAll('_', ' ')}</span>
</span>

<style>
  .country-label { display: inline-flex; align-items: center; gap: 8px; min-width: 0; }
  img { flex-shrink: 0; width: 20px; height: 14px; border-radius: 3px; object-fit: cover; }
  span span { overflow-wrap: anywhere; }
</style>
