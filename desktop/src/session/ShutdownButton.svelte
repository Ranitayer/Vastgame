<script lang="ts">
  import Button from '../components/Button.svelte';
  import { launch, shutdown } from './launch.svelte';
</script>
<Button icon variant="inverse" size="large"
  aria-label={launch.shutdownRequested || launch.busy ? 'Force shut down this rig' : 'Shut down this rig'}
  title={launch.shutdownRequested || launch.busy ? 'Force shutdown — unbacked saves may be lost' : 'Shut down this rig'}
  onclick={shutdown}>
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17"/></svg>
</Button>
<style>
  svg { width: 24px; height: 24px; }
</style>
