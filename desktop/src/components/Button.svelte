<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { HTMLButtonAttributes } from 'svelte/elements';
  let { children, variant = 'tonal', tone = 'neutral', size = 'normal', icon = false, full = false, selected = false,
    element = $bindable<HTMLButtonElement | undefined>(), class: className = '', ...attributes }: HTMLButtonAttributes & {
      children: Snippet; variant?: 'tonal' | 'plain' | 'outline' | 'inverse' | 'tab' | 'surface';
      tone?: 'neutral' | 'blue' | 'red' | 'green';
      size?: 'small' | 'normal' | 'large'; icon?: boolean; full?: boolean; selected?: boolean; element?: HTMLButtonElement;
    } = $props();
</script>
<button type="button" {...attributes} bind:this={element} class={`control ${className}`} class:icon class:full class:selected data-variant={variant} data-tone={tone} data-size={size}>
  <span class="face">{@render children()}</span>
</button>
<style>
  .control { --size: var(--button-size); flex-shrink: 0; width: auto; min-width: var(--size); height: var(--size); padding: 0; border: 0; border-radius: 99px; background: transparent; color: var(--text); font: inherit; font-size: 12px; cursor: pointer; }
  .control[data-size='small'] { --size: 32px; }
  .control[data-size='large'] { --size: 48px; }
  .control.icon { width: var(--size); }
  .control.full { width: 100%; }
  .control:hover, .control:active { background: transparent; }
  .face { display: flex; align-items: center; justify-content: center; gap: 8px; width: 100%; height: 100%; padding: 0 14px; border: 1px solid transparent; border-radius: inherit; background: var(--surface-hover); color: inherit; pointer-events: none; transition: background-color var(--button-duration) ease-out, color var(--button-duration) ease-out, border-color var(--button-duration) ease-out; }
  .icon .face { padding: 0; }
  .control[data-variant='surface'] .face { background: var(--surface); }
  .control:not(:disabled):hover .face, .control:not(:disabled):focus-visible .face { background: var(--surface-active); }
  .control[data-variant='tonal'].selected .face { background: var(--surface-active); }
  .control[data-variant='plain'] .face, .control[data-variant='tab'] .face { background: transparent; }
  .control[data-variant='plain']:hover .face, .control[data-variant='plain']:focus-visible .face, .control[data-variant='plain'].selected .face,
  .control[data-variant='tab']:hover .face, .control[data-variant='tab']:focus-visible .face { background: var(--surface-active); }
  .control[data-variant='outline'] .face { border-color: var(--accent); background: transparent; color: var(--text); }
  .control[data-variant='outline']:hover .face, .control[data-variant='outline']:focus-visible .face { background: var(--surface-active); }
  .control[data-variant='outline'].selected .face, .control[data-variant='tab'].selected .face { background: var(--accent); color: var(--text); }
  .control[data-variant='inverse'] .face { background: var(--text); color: var(--surface); }
  .control[data-variant='inverse']:hover .face, .control[data-variant='inverse']:focus-visible .face { background: var(--surface); color: var(--text); }
  .control[data-tone='blue'] { --action-fill: var(--action-blue); --action-hover: var(--action-blue-hover); }
  .control[data-tone='red'] { --action-fill: var(--action-red); --action-hover: var(--action-red-hover); }
  .control[data-tone='green'] { --action-fill: var(--action-green); --action-hover: var(--action-green-hover); }
  .control:not([data-tone='neutral']) .face { background: var(--action-fill); color: var(--text); }
  .control:not([data-tone='neutral']):not(:disabled):hover .face,
  .control:not([data-tone='neutral']):not(:disabled):focus-visible .face { background: var(--action-hover); }
  .control:disabled { opacity: 0.5; cursor: default; }
  @media (prefers-reduced-motion: reduce) { .face { transition: none; } }
</style>
