<script lang="ts">
  import Button from '../components/Button.svelte';
  import GameArtwork from './GameArtwork.svelte';
  import type { Game } from './types';
  let { game, selected, onclick }: { game: Game; selected: boolean; onclick: () => void } = $props();
</script>
<article class="game-card" class:selected>
  <div class="cover">
    <button class="open" onclick={onclick} aria-label={`View ${game.name}`} title={game.name} aria-expanded={selected} aria-controls="game-details"><GameArtwork name={game.name} appid={game.steam_appid}/></button>
    <div class="gear"><Button icon size="small" variant="surface" aria-label={`Settings for ${game.name} (coming soon)`} title="Settings coming soon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.5 3h5l.5 2 2 1.2 2-.6 2.5 4.3L20 11.5v2l1.5 1.6L19 19.4l-2-.6-2 1.2-.5 2h-5L9 20l-2-1.2-2 .6-2.5-4.3L4 13.5v-2L2.5 9.9 5 5.6l2 .6L9 5Z"/><circle cx="12" cy="12.5" r="3"/></svg></Button></div>
  </div>
</article>
<style>
  .game-card { width: 100%; max-width: var(--game-card-width); min-width: 0; align-self: start; padding: var(--game-card-inset); border-radius: 24px; background-color: transparent; transition: background-color 180ms ease-out; }
  .game-card:hover, .game-card:has(:focus-visible) { background-color: var(--surface-hover); }
  .open { display: block; width: 100%; height: auto; padding: 0; border-radius: 16px; background: transparent; color: var(--text); cursor: pointer; }
  .cover { position: relative; width: 100%; border-radius: 16px; }
  .selected .cover { outline: 2px solid var(--accent); outline-offset: -2px; }
  .gear { position: absolute; right: var(--game-card-inset); bottom: var(--game-card-inset); }
  @media (prefers-reduced-motion: reduce) { .game-card { transition: none; } }
</style>
