<script lang="ts">
  import { onMount, untrack } from 'svelte';
  import { library } from './catalog.svelte';
  import { artwork } from './artwork';
  let { name, gameId, kind = 'cover' }: { name: string; gameId: string; kind?: 'cover' | 'banner' } = $props();
  let root: HTMLDivElement;
  let visible = $state(false);
  let image = $state<string | null>(null);
  const initials = $derived(name.split(/[\s_-]+/).filter(Boolean).slice(0, 2).map(word => word[0]).join('').toUpperCase());
  onMount(() => {
    const observer = new IntersectionObserver(entries => {
      visible = entries.some(entry => entry.isIntersecting);
    }, { rootMargin: '200px' });
    observer.observe(root);
    return () => observer.disconnect();
  });
  let lastKey = '';
  $effect(() => {
    library.revision;
    const key = `${gameId}-${kind}`;
    if (lastKey !== key) { image = null; lastKey = key; }
    if (!visible) { image = null; return; }
    if (!gameId || untrack(() => image) !== null) return;
    let current = true;
    void artwork(gameId, kind).then(value => { if (current) image = value; });
    return () => { current = false; };
  });
</script>
{#snippet placeholder()}
  <div class="placeholder"><svg viewBox="0 0 48 48"><path d="M15 16h18c6 0 10 20 5 21-3 1-6-5-9-5H19c-3 0-6 6-9 5-5-1-1-21 5-21Z M16 21v10m-5-5h10 M32 22h.01M37 27h.01"/></svg><span>{initials}</span></div>
{/snippet}
<div class="artwork" class:banner={kind === 'banner'} bind:this={root} aria-hidden="true">
  {#if image}<img src={image} alt="" decoding="async" onerror={() => image = null}/>
  {:else}{@render placeholder()}{/if}
</div>
<style>
  .artwork { position: relative; width: 100%; aspect-ratio: 2 / 3; border-radius: 16px; overflow: hidden; background: var(--surface-active); color: var(--text-muted); }
  .artwork.banner { aspect-ratio: auto; min-height: 72px; border-radius: 0; background: var(--surface-hover); }
  img { display: block; width: 100%; height: 100%; object-fit: cover; }
  .banner img { height: auto; max-height: min(270px, 30cqh); object-fit: contain; object-position: top; }
  .placeholder { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 14px; }
  svg { width: 42%; height: auto; max-width: 64px; stroke-width: 1.5; }
  span { font-size: 24px; font-weight: 600; letter-spacing: 0.08em; }
</style>
