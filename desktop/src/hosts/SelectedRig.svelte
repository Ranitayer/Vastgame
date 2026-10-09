<script lang="ts">
  import RigSummary from './RigSummary.svelte';
  import { hostSummary, type Host } from './types';
  let { host, wide = false }: { host: Host; wide?: boolean } = $props();
</script>
<div class="rig-pill" class:wide role="status" aria-label={`Selected rig: ${hostSummary(host)}`} title={hostSummary(host)}><RigSummary {host} large={wide}/></div>
<style>
  .rig-pill { display: inline-flex; align-items: center; height: 30px; padding: 0 10px; min-width: 0; max-width: 100%; border-radius: 99px; background: var(--surface-hover); color: var(--text); }
  .rig-pill.wide { width: 100%; height: var(--button-size); padding: 0 var(--page-margin); }
</style>
