<script lang="ts">
  import Range from '../components/Range.svelte';
  import { price } from './types';
  let { limit = $bindable<number | null>(null), ceiling, disabled = false }: { limit?: number | null; ceiling: number; disabled?: boolean } = $props();
  const text = $derived(limit === null || limit >= ceiling ? 'Any price' : `${price(limit)} / hr max`);
</script>
<Range max={ceiling} step={0.01} {disabled} label="Maximum hourly price in US dollars" {text} bind:value={() => limit ?? ceiling, value => limit = value}/>
