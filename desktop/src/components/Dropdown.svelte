<script lang="ts">
  import { onMount, tick } from 'svelte';
  let { value = $bindable(''), options, label, placeholder }: { value?: string; options: string[]; label: string; placeholder: string } = $props();
  let open = $state(false);
  let root: HTMLDivElement;
  let trigger: HTMLButtonElement;
  const choices = $derived(['', ...options]);
  async function show(index = choices.indexOf(value)) {
    open = true;
    await tick();
    root.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')[Math.max(0, index)]?.focus();
  }
  function close() { open = false; trigger.focus(); }
  function keyboard(event: KeyboardEvent) {
    if (event.key === 'Escape' && open) { event.preventDefault(); event.stopPropagation(); close(); }
    if (!open || !['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const items = [...root.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')];
    const current = items.indexOf(document.activeElement as HTMLButtonElement);
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 :
      (current + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[index]?.focus();
  }
  onMount(() => {
    const outside = (event: PointerEvent) => { if (!root.contains(event.target as Node)) open = false; };
    const unfocus = (event: FocusEvent) => { if (!root.contains(event.target as Node)) open = false; };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('focusin', unfocus);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('focusin', unfocus); };
  });
</script>

<div class="dropdown" bind:this={root} onkeydown={keyboard} role="group" aria-label={label}>
  <button class="trigger" bind:this={trigger} aria-haspopup="menu" aria-expanded={open}
    onclick={() => open ? close() : void show()}
    onkeydown={(event) => { if (!open && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) { event.preventDefault(); event.stopPropagation(); void show(event.key === 'ArrowUp' ? choices.length - 1 : undefined); } }}>
    <span>{value || placeholder}</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"/></svg>
  </button>
  {#if open}
    <div class="menu" role="menu" aria-label={label}>
      {#each choices as item (item)}
        <button role="menuitemradio" aria-checked={value === item} class:selected={value === item}
          onclick={() => { value = item; close(); }}>
          <span>{item || placeholder}</span>
          {#if value === item}<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4 10-10"/></svg>{/if}
        </button>
      {/each}
    </div>
  {/if}
</div>

<style>
  .dropdown { position: relative; width: 240px; max-width: 100%; flex-shrink: 0; }
  .trigger { width: 100%; height: 44px; padding: 0 14px; border-radius: 16px; display: flex; align-items: center; justify-content: space-between; background: var(--surface-hover); color: var(--text); font: inherit; font-size: 13px; }
  .trigger:hover, .trigger[aria-expanded='true'] { background: var(--surface-active); }
  svg { flex-shrink: 0; color: var(--text-muted); }
  .menu { position: absolute; top: calc(100% + 8px); left: 0; width: 100%; z-index: 10; padding: 6px; display: grid; gap: 4px; border-radius: 18px; background: var(--surface-hover); box-shadow: 0 0 0 1px var(--surface-active), 0 8px 24px var(--surface); }
  .menu button { width: 100%; height: 36px; padding: 0 10px; border-radius: 12px; display: flex; align-items: center; justify-content: space-between; font: inherit; font-size: 13px; color: var(--text); }
  .menu button:hover, .menu button.selected { background: var(--surface-active); }
</style>
