<script lang="ts">
  import type { Snippet } from 'svelte';
  import { fade } from 'svelte/transition';
  let { open, anchor, label, onclose, children, menu = false, above = false, persistent = false }: { open: boolean; anchor: HTMLElement | undefined; label: string; onclose: () => void; children: Snippet; menu?: boolean; above?: boolean; persistent?: boolean } = $props();
  const duration = globalThis.matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 140;
  $effect(() => { if (!open || menu || persistent) return; const timer = setTimeout(onclose, 2000); return () => clearTimeout(timer); });
  function place(node: HTMLDivElement) {
    document.body.appendChild(node);
    function position() {
      if (!anchor) return;
      const margin = parseFloat(getComputedStyle(node).getPropertyValue('--page-margin')) || 12;
      const rect = anchor.getBoundingClientRect();
      if (menu) node.style.width = `${Math.min(innerWidth - margin * 2, Math.max(240, rect.width))}px`;
      const width = node.offsetWidth, height = node.offsetHeight;
      const right = rect.right + 8;
      const preferredLeft = menu ? rect.left + (rect.width - width) / 2 : right + width <= innerWidth - margin ? right : rect.left - width - 8;
      const left = Math.max(margin, Math.min(innerWidth - width - margin, preferredLeft));
      const below = rect.bottom + 8;
      const preferredTop = menu ? !above && below + height <= innerHeight - margin ? below : rect.top - height - 8 : rect.top + (rect.height - height) / 2;
      const top = Math.max(margin, Math.min(innerHeight - height - margin, preferredTop));
      node.style.left = `${left}px`; node.style.top = `${top}px`;
    }
    const observer = new ResizeObserver(position);
    observer.observe(node);
    if (anchor) observer.observe(anchor);
    const outside = (event: PointerEvent) => { if (!node.contains(event.target as Node) && !anchor?.contains(event.target as Node)) onclose(); };
    const keyboard = (event: KeyboardEvent) => { if (event.key === 'Escape') { event.stopPropagation(); event.preventDefault(); onclose(); anchor?.focus(); } };
    window.addEventListener('resize', position);
    document.addEventListener('scroll', position, true);
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', keyboard, true);
    position();
    return { destroy() { observer.disconnect(); window.removeEventListener('resize', position); document.removeEventListener('scroll', position, true); document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', keyboard, true); node.remove(); } };
  }
</script>
{#if open}<div class="popover" class:menu use:place transition:fade={{ duration: menu ? 0 : duration }} role={menu ? "menu" : "dialog"} aria-label={label}>{@render children()}</div>{/if}
<style>
  .popover { position: fixed; z-index: 1000; width: 320px; max-width: calc(100vw - var(--page-margin) * 2); max-height: calc(100vh - var(--page-margin) * 2); overflow: auto; padding: var(--page-margin); border: 1px solid var(--surface-active); border-radius: 20px; background: var(--surface-hover); color: var(--text); box-shadow: 0 6px 20px var(--surface); font-size: 12px; line-height: 1.5; }
  .popover.menu { padding: 6px; overflow: hidden; }
  .popover :global(p) { margin: 0; }
</style>
