<script lang="ts">
  import { tabs, type TabId } from '../navigation';

  let { active = $bindable('home') }: { active?: TabId } = $props();

  function navigate(event: KeyboardEvent, index: number) {
    let next: number;
    switch (event.key) {
      case 'ArrowRight': next = (index + 1) % tabs.length; break;
      case 'ArrowLeft': next = (index + tabs.length - 1) % tabs.length; break;
      case 'Home': next = 0; break;
      case 'End': next = tabs.length - 1; break;
      default: return;
    }
    event.preventDefault();
    active = tabs[next].id;
    const button = event.currentTarget as HTMLButtonElement;
    button.parentElement?.querySelector<HTMLButtonElement>(`#tab-${active}`)?.focus();
  }
</script>

<div class="tabs" role="tablist" aria-label="Main navigation" aria-orientation="horizontal">
  {#each tabs as tab, index (tab.id)}
    <button
      id={`tab-${tab.id}`}
      role="tab"
      aria-label={tab.label}
      title={tab.label}
      class:selected={active === tab.id}
      aria-selected={active === tab.id}
      aria-controls={`panel-${tab.id}`}
      tabindex={active === tab.id ? 0 : -1}
      onclick={() => active = tab.id}
      onkeydown={(event) => navigate(event, index)}
    >
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d={tab.icon} /></svg>
      <span>{tab.label}</span>
    </button>
  {/each}
</div>

<style>
  .tabs {
    display: flex;
    gap: 4px;
    padding: 2px;
    overflow-x: auto;
    scrollbar-width: thin;
    scrollbar-color: var(--surface-active) var(--surface-hover);
  }
  button {
    flex: 0 0 auto;
    width: auto;
    height: 36px;
    padding: 0 12px;
    border-radius: 12px;
    display: flex;
    justify-content: center;
    align-items: center;
    gap: 7px;
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    white-space: nowrap;
  }
  svg { width: 16px; height: 16px; }
  button:hover, button:active { background: var(--surface-active); color: var(--text); }
  button.selected { background: var(--accent); color: var(--text); }
  @media (max-width: 840px) {
    button { width: 36px; padding: 0; }
    span { display: none; }
  }
</style>
