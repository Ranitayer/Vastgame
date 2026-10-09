<script lang="ts">
  import Button from './Button.svelte';
  import Popover from './Popover.svelte';
  import { tick } from 'svelte';
  let { value = $bindable(''), options, label, placeholder, up = false }: { value?: string; options: (string | { value: string; label: string })[]; label: string; placeholder: string; up?: boolean } = $props();
  let open = $state(false), query = $state(''), page = $state(0), height = $state(600);
  let trigger = $state<HTMLButtonElement>();
  let contents: HTMLDivElement | undefined;
  const choices = $derived([{ value: '', label: placeholder }, ...options.map(item => typeof item === 'string' ? { value: item, label: item } : item)]);
  const filtered = $derived(choices.filter(item => item.label.toLowerCase().includes(query.trim().toLowerCase())));
  const pageSize = $derived(Math.max(1, Math.min(8, Math.floor((height - 144) / 44))));
  const pages = $derived(Math.max(1, Math.ceil(filtered.length / pageSize)));
  const visible = $derived(filtered.slice(page * pageSize, (page + 1) * pageSize));
  $effect(() => { query; options; page = 0; });
  $effect(() => { if (page >= pages) page = pages - 1; });
  function items() { return [...(contents?.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]') ?? [])]; }
  async function show(last = false) {
    height = innerHeight; query = ''; open = true;
    await tick();
    const selected = choices.findIndex(item => item.value === value);
    page = last ? pages - 1 : Math.floor(Math.max(0, selected) / pageSize);
    await tick();
    const buttons = items();
    buttons[last ? buttons.length - 1 : Math.max(0, selected) % pageSize]?.focus();
  }
  function close() { open = false; trigger?.focus(); }
  async function movePage(next: number) {
    page = Math.max(0, Math.min(pages - 1, next)); await tick(); items()[0]?.focus();
  }
  function keyboard(event: KeyboardEvent) {
    if (event.target instanceof HTMLInputElement && !['ArrowDown', 'ArrowUp', 'Escape'].includes(event.key)) return;
    if (event.key === 'PageDown' || event.key === 'PageUp') { event.preventDefault(); void movePage(page + (event.key === 'PageDown' ? 1 : -1)); return; }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const buttons = items(); if (!buttons.length) return;
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === 'Home') { void movePage(0); return; }
    if (event.key === 'End') { void movePage(pages - 1).then(() => items().at(-1)?.focus()); return; }
    if (event.key === 'ArrowDown' && index === buttons.length - 1 && page < pages - 1) { void movePage(page + 1); return; }
    if (event.key === 'ArrowUp' && index === 0 && page > 0) { void movePage(page - 1).then(() => items().at(-1)?.focus()); return; }
    buttons[index < 0 ? event.key === 'ArrowUp' ? buttons.length - 1 : 0 : (index + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length]?.focus();
  }
</script>
<svelte:window onresize={() => height = innerHeight}/>
<div class="dropdown">
  <Button full bind:element={trigger} selected={open} title={choices.find(item => item.value === value)?.label || placeholder} aria-label={label} aria-haspopup="menu" aria-expanded={open}
    onclick={() => open ? close() : void show()}
    onkeydown={(event) => { if (!open && ['ArrowDown', 'ArrowUp'].includes(event.key)) { event.preventDefault(); event.stopPropagation(); void show(event.key === 'ArrowUp'); } }}>
    <span>{choices.find(item => item.value === value)?.label || placeholder}</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d={up ? 'm7 14 5-5 5 5' : 'm7 10 5 5 5-5'}/></svg>
  </Button>
</div>
<Popover {open} anchor={trigger} {label} menu above={up} onclose={close}>
  <div class="choices" bind:this={contents} onkeydown={keyboard} role="group" aria-label={label}>
    {#if choices.length > pageSize}<input type="search" bind:value={query} aria-label={`Search ${label.toLowerCase()}`} placeholder="Search choices"/>{/if}
    {#each visible as item (item.value)}
      <Button full variant="plain" role="menuitemradio" title={item.label} aria-checked={value === item.value} selected={value === item.value} onclick={() => { value = item.value; close(); }}>
        <span>{item.label}</span>{#if value === item.value}<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4 10-10"/></svg>{/if}
      </Button>
    {/each}
    {#if !filtered.length}<p role="status">No matching choices</p>{/if}
    {#if pages > 1}<div class="pages"><Button icon size="small" variant="plain" aria-label="Previous choices" disabled={page === 0} onclick={() => void movePage(page - 1)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 6-6 6 6 6"/></svg></Button><span aria-live="polite">{page + 1} / {pages}</span><Button icon size="small" variant="plain" aria-label="Next choices" disabled={page === pages - 1} onclick={() => void movePage(page + 1)}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m10 6 6 6-6 6"/></svg></Button></div>{/if}
  </div>
</Popover>
<style>
  .dropdown { width: 240px; max-width: 100%; min-width: 0; flex-shrink: 0; }
  .dropdown :global(.face), .choices :global(.face) { justify-content: space-between; }
  span { min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  svg { flex-shrink: 0; color: var(--text-muted); }
  .choices { display: grid; gap: 4px; }
  input { width: 100%; min-width: 0; height: 36px; padding: 0 14px; border: 0; border-radius: 99px; background: var(--surface-active); color: var(--text); font: inherit; }
  .pages { display: flex; align-items: center; justify-content: space-between; color: var(--text-muted); }
  p { margin: 8px; font-size: 12px; color: var(--text-muted); }
</style>
