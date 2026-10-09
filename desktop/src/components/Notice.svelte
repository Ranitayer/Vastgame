<script lang="ts">
  import Popover from './Popover.svelte';
  let { text, detail = text, anchor }: { text: string; detail?: string; anchor: HTMLElement | undefined } = $props();
  let open = $state(true);
  $effect(() => { text; detail; open = true; });
</script>
{#key text}<Popover {open} {anchor} label="Information" onclose={() => open = false}><p role="status" title={detail}>{text}</p></Popover>{/key}
