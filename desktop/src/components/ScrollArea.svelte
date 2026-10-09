<script lang="ts">
  import { onMount, type Snippet } from 'svelte';
  let { children, separated = false, label }: { children: Snippet; separated?: boolean; label: string } = $props();
  let viewport: HTMLDivElement;
  let content: HTMLDivElement;
  let thumb = $state({ height: 0, top: 0, visible: false });
  onMount(() => {
    function update() {
      const height = viewport.clientHeight;
      const total = viewport.scrollHeight;
      const size = Math.min(height, Math.max(20, height * height / Math.max(1, total)));
      thumb = { height: size, top: Math.max(0, viewport.scrollTop) / Math.max(1, total - height) * (height - size), visible: total > height + 1 };
    }
    const observer = new ResizeObserver(update);
    observer.observe(viewport);
    observer.observe(content);
    viewport.addEventListener('scroll', update, { passive: true });
    update();
    return () => { observer.disconnect(); viewport.removeEventListener('scroll', update); };
  });
</script>

<div class="scroll-area" class:separated>
  <div class="viewport" bind:this={viewport} role="region" aria-label={label} tabindex="0">
    <div class="content" bind:this={content}>{@render children()}</div>
  </div>
  {#if thumb.visible}<div class="indicator" aria-hidden="true"><div style:height={`${thumb.height}px`} style:transform={`translateY(${thumb.top}px)`}></div></div>{/if}
</div>

<style>
  .scroll-area { position: relative; min-width: 0; min-height: 0; height: 100%; }
  .scroll-area.separated { padding-right: var(--page-margin); }
  .viewport { height: 100%; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: none; }
  .viewport::-webkit-scrollbar { display: none; }
  .viewport:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; border-radius: 16px; }
  .content { display: flow-root; padding-bottom: 2px; }
  .indicator { position: absolute; top: 0; bottom: 0; right: calc(var(--page-margin) / -2 - 2px); width: 4px; pointer-events: none; user-select: none; }
  .separated .indicator { right: calc(var(--page-margin) / 2 - 2px); }
  .indicator div { width: 4px; border-radius: 4px; background: var(--surface-active); }
</style>
