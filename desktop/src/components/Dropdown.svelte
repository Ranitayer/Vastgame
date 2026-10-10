<script lang="ts">
  import Button from './Button.svelte';
  import Popover from './Popover.svelte';
  import { tick } from 'svelte';
  let { value = $bindable(''), options, label, placeholder, up = false }: { value?: string; options: (string | { value: string; label: string })[]; label: string; placeholder: string; up?: boolean } = $props();
  let open = $state(false), query = $state('');
  let trigger = $state<HTMLButtonElement>();
  let contents: HTMLDivElement | undefined;
  let list: HTMLDivElement | undefined;
  const choices = $derived([{ value: '', label: placeholder }, ...options.map(item => typeof item === 'string' ? { value: item, label: item } : item)]);
  const filtered = $derived(choices.filter(item => item.label.toLowerCase().includes(query.trim().toLowerCase())));
  $effect(() => { query; options; if (list) list.scrollTop = 0; });
  function items() { return [...(contents?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? [])]; }
  function focus(button?: HTMLButtonElement) {
    button?.focus({ preventScroll: true });
    button?.scrollIntoView({ block: 'nearest' });
  }
  async function show(last = false) {
    query = ''; open = true;
    await tick();
    const buttons = items();
    focus(buttons[last ? buttons.length - 1 : Math.max(0, choices.findIndex(item => item.value === value))]);
  }
  function close() { open = false; trigger?.focus(); }
  function keyboard(event: KeyboardEvent) {
    if (event.target instanceof HTMLInputElement && !['ArrowDown', 'ArrowUp', 'Escape'].includes(event.key)) return;
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End', 'PageDown', 'PageUp'].includes(event.key)) return;
    event.preventDefault();
    const buttons = items(); if (!buttons.length) return;
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const jump = Math.max(1, Math.floor((list?.clientHeight ?? 44) / 44));
    let next = index < 0 ? event.key === 'ArrowUp' ? buttons.length - 1 : 0 : index;
    if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = buttons.length - 1;
    else if (event.key === 'PageDown' || event.key === 'PageUp') next = Math.max(0, Math.min(buttons.length - 1, next + (event.key === 'PageDown' ? jump : -jump)));
    else if (index >= 0) next = (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length;
    focus(buttons[next]);
  }

</script>
<div class="dropdown">
  <Button full bind:element={trigger} selected={open} title={choices.find(item => item.value === value)?.label || placeholder} aria-label={label} aria-haspopup="menu" aria-expanded={open}
    onclick={() => open ? close() : void show()}
    onkeydown={(event) => { if (!open && ['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); event.stopPropagation(); void show(event.key === 'ArrowUp'); } }}>
    <span>{choices.find(item => item.value === value)?.label || placeholder}</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d={up ? 'm7 14 5-5 5 5' : 'm7 10 5 5 5-5'}/></svg>
  </Button>
</div>
<Popover {open} anchor={trigger} {label} menu above={up} onclose={close}>
  <div class="choices" bind:this={contents} onkeydown={keyboard} role="group" aria-label={label}>
    {#if choices.length > 8}<input type="search" bind:value={query} aria-label={`Search ${label.toLowerCase()}`} placeholder="Search choices"/>{/if}
    <div class="items" bind:this={list}>
    {#each filtered as item (item.value)}
      <Button full variant="plain" role="menuitemradio" title={item.label} aria-checked={value === item.value} selected={value === item.value} onclick={() => { value = item.value; close(); }}>
        <span>{item.label}</span>{#if value === item.value}<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4 10-10"/></svg>{/if}
      </Button>
    {/each}
    {#if !filtered.length}<p role="status">No matching choices</p>{/if}
    </div>
  </div>
</Popover>
<style>
  .dropdown { width: 240px; max-width: 100%; min-width: 0; flex-shrink: 0; }
  .dropdown :global(.face), .choices :global(.face) { justify-content: space-between; }
  span { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  svg { flex-shrink: 0; color: var(--text-muted); }
  .choices { display: flex; flex-direction: column; gap: 4px; max-height: min(420px, calc(100dvh - var(--page-margin) * 2 - 14px)); }
  .items { display: grid; gap: 4px; min-height: 0; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: none; }
  .items::-webkit-scrollbar { display: none; }
  input { flex-shrink: 0; width: 100%; min-width: 0; height: 36px; padding: 0 14px; border: 0; border-radius: 99px; background: var(--surface-active); color: var(--text); font: inherit; }
  p { margin: 8px; font-size: 12px; color: var(--text-muted); }
</style>
