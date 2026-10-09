<script lang="ts">
  import Button from './Button.svelte';
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
    <Button variant="tab"
      id={`tab-${tab.id}`}
      role="tab"
      aria-label={tab.label}
      title={tab.label}
      selected={active === tab.id}
      aria-selected={active === tab.id}
      aria-controls={`panel-${tab.id}`}
      tabindex={active === tab.id ? 0 : -1}
      onclick={() => active = tab.id}
      onkeydown={(event) => navigate(event, index)}
    >
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d={tab.icon} /></svg>
      <span class="label">{tab.label}</span>
    </Button>
  {/each}
</div>

<style>
  .tabs {
    display: flex;
    gap: 4px;
    padding: 4px;
    overflow: visible;
  }
  svg { width: 16px; height: 16px; }
  @media (max-width: 1450px) { .label { display: none; } .tabs :global(.face) { padding: 0; } }
</style>
