<script lang="ts">
  import Button from '../components/Button.svelte';
  import Popover from '../components/Popover.svelte';
  import { launch, shutdown } from './launch.svelte';
  let open = $state(false);
  let anchor = $state<HTMLButtonElement>();
  $effect(() => { launch.jobId; open = false; });
  function confirm() {
    if (!launch.instanceId || launch.connecting || launch.stopping) return;
    if (open && launch.instanceId && !launch.stopping) { open = false; shutdown(); }
    else open = !open;
  }
</script>
<Button icon variant="inverse" size="large" bind:element={anchor} aria-haspopup="dialog" aria-expanded={open}
  aria-label="Shut down this rig" title="Shut down this rig"
  disabled={launch.stopping || launch.connecting || !launch.instanceId} onclick={confirm}>
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg>
</Button>
<Popover {open} {anchor} label="Confirm rig shutdown" onclose={() => open = false}><p>Click again to shut down this rig.</p></Popover>
<style>
  svg { width: 24px; height: 24px; }
</style>
