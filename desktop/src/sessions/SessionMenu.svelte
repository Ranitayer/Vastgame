<script lang="ts">
  import { tick } from 'svelte';
  import Button from '../components/Button.svelte';
  import Popover from '../components/Popover.svelte';
  import Notice from '../components/Notice.svelte';
  import { copyText } from '../components/clipboard';
  import { copySessionLogs } from './archive';
  let { id, name }: { id: string; name: string } = $props();
  let open = $state(false), copying = $state(false), notice = $state('');
  let anchor = $state<HTMLButtonElement>();
  let menu: HTMLDivElement;
  function close() { open = false; anchor?.focus(); }
  async function show() { open = true; await tick(); menu?.querySelector<HTMLButtonElement>('button')?.focus(); }
  async function copy(logs: boolean) {
    close(); notice = ''; copying = true;
    try {
      if (logs) { const complete = await copySessionLogs(id); notice = complete ? 'Session logs copied' : 'Saved logs copied; older output was not recorded'; }
      else { await copyText(id); notice = 'Session ID copied'; }
    } catch (error) { notice = String(error); }
    finally { copying = false; }
  }
  function keyboard(event: KeyboardEvent) {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const buttons = [...menu.querySelectorAll<HTMLButtonElement>('button')];
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    buttons[event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowUp' ? -1 : 1) + buttons.length) % buttons.length]?.focus();
  }
</script>
<Button icon variant="surface" bind:element={anchor} selected={open} disabled={copying} title="Session options" aria-label={`Options for ${name}`} aria-haspopup="menu" aria-expanded={open} onclick={() => open ? close() : void show()} onkeydown={(event) => { if (!open && ['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); void show(); } }}><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg></Button>
<Popover {open} {anchor} label="Session options" menu onclose={close}>
  <div class="choices" bind:this={menu} role="group" aria-label="Copy session data">
    <Button full variant="plain" role="menuitem" onkeydown={keyboard} onclick={() => void copy(true)}>Copy session logs</Button>
    <Button full variant="plain" role="menuitem" onkeydown={keyboard} onclick={() => void copy(false)}>Copy session ID</Button>
  </div>
</Popover>
{#if notice}<Notice {anchor} text={notice}/>{/if}
<style>
  .choices { display: grid; gap: 4px; }
  svg { fill: currentColor; stroke: none; }
</style>
