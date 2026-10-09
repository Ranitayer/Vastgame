<script lang="ts">
  import { onMount } from 'svelte';
  import { getCurrentWindow } from '@tauri-apps/api/window';
  import TabBar from './components/TabBar.svelte';
  import HostsPage from './hosts/HostsPage.svelte';
  import { tabs, type TabId } from './navigation';

  const window = getCurrentWindow();
  let error = $state('');
  let edgeToEdge = $state(false);
  let activeTab = $state<TabId>('home');

  onMount(() => {
    let disposed = false;
    let revision = 0;
    let unlisten: (() => void) | undefined;
    async function updateFrame() {
      const current = ++revision;
      try {
        const [maximized, fullscreen] = await Promise.all([
          window.isMaximized(), window.isFullscreen(),
        ]);
        if (!disposed && current === revision) edgeToEdge = maximized || fullscreen;
      } catch {
        if (!disposed) error = 'Window layout unavailable. Reopen Vastgame to retry.';
      }
    }
    window.onResized(updateFrame).then((stop) => {
      if (disposed) stop();
      else { unlisten = stop; void updateFrame(); }
    }).catch(() => {
      if (!disposed) error = 'Window layout unavailable. Reopen Vastgame to retry.';
    });
    return () => { disposed = true; unlisten?.(); };
  });

  async function control(action: 'minimize' | 'toggleMaximize' | 'close') {
    try {
      await window[action]();
      error = '';
    } catch {
      error = 'Window control unavailable. Use your system window controls.';
    }
  }
</script>

<div class="shell" class:edge-to-edge={edgeToEdge}>
  <header class="titlebar">
    <div class="drag-region" data-tauri-drag-region>
      <span data-tauri-drag-region>Vastgame</span>
    </div>
    <div class="navigation"><TabBar bind:active={activeTab} /></div>
    <div class="window-controls" aria-label="Window controls">
      <button aria-label="Minimize" title="Minimize" onclick={() => control('minimize')}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 12h12" /></svg>
      </button>
      <button aria-label="Maximize or restore" title="Maximize or restore" onclick={() => control('toggleMaximize')}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2" /></svg>
      </button>
      <button aria-label="Close" title="Close" onclick={() => control('close')}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 7 10 10M17 7 7 17" /></svg>
      </button>
    </div>
  </header>
  <main aria-label="Vastgame workspace">
    {#if error}<p role="alert">{error}</p>{/if}
    {#each tabs as tab (tab.id)}
      <div
        class="tab-panel"
        id={`panel-${tab.id}`}
        role="tabpanel"
        aria-labelledby={`tab-${tab.id}`}
        hidden={activeTab !== tab.id}
        tabindex="0"
      >{#if tab.id === 'hosts'}<HostsPage active={activeTab === 'hosts'}/>{/if}</div>
    {/each}
  </main>
</div>
