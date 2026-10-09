<script lang="ts">
  import Button from '../components/Button.svelte';
  import { launch, shutdown } from './launch.svelte';
</script>
<Button icon variant="inverse" size="large"
  aria-label="Shut down this rig" title="Shut down this rig"
  disabled={launch.stopping || launch.connecting || !launch.instanceId} onclick={shutdown}>
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg>
</Button>
<style>
  svg { width: 24px; height: 24px; }
</style>
