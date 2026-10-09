<script lang="ts">
  import Button from '../components/Button.svelte';
  import RigSummary from './RigSummary.svelte';
  import HostSpecs from './HostSpecs.svelte';
  import { hostSummary, type Host } from './types';
  let { host, expanded, chosen, ontoggle, onchoose }: { host: Host; expanded: boolean; chosen: boolean; ontoggle: () => void; onchoose: () => void } = $props();
</script>
<article class="host-pill">
  <div class="selection"><Button full selected={chosen} aria-label={`${chosen ? 'Deselect' : 'Select'} rig: ${hostSummary(host, true, false)}`} title={hostSummary(host, true, false)} aria-pressed={chosen} onclick={onchoose}><span aria-hidden="true"></span></Button></div>
  <div class="contents">
    <div class="info"><RigSummary {host} download disk={false} highlightPrice/></div>
    {#if expanded}<div class="expanded" id={`home-host-${host.id}`}><HostSpecs {host}/></div>{/if}
  </div>
  <div class="expand-control"><Button icon size="small" variant="surface" aria-label={`${expanded ? 'Collapse' : 'Expand'} rig details`} title={`${expanded ? 'Collapse' : 'Expand'} rig details`} aria-expanded={expanded} aria-controls={expanded ? `home-host-${host.id}` : undefined} onclick={ontoggle}><svg viewBox="0 0 24 24" aria-hidden="true"><path d={expanded ? 'm7 14 5-5 5 5' : 'm7 10 5 5 5-5'}/></svg></Button></div>
</article>
<style>
  .host-pill { position: relative; min-width: 0; border-radius: 20px; overflow: hidden; }
  .selection { position: absolute; inset: 0; }
  .selection :global(.control) { width: 100%; height: 100%; border-radius: 20px; }
  .contents { position: relative; pointer-events: none; }
  .info { container: host-pill-info / inline-size; display: flex; align-items: center; height: var(--button-size); min-width: 0; overflow: hidden; padding: 0 calc(32px + var(--page-margin)) 0 var(--page-margin); }
  .expanded { padding: var(--page-margin); }
  .expand-control { position: absolute; top: calc((var(--button-size) - 32px) / 2); right: 4px; }
</style>
