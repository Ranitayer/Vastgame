<script lang="ts">
  import { Channel, invoke } from '@tauri-apps/api/core';
  import { tick } from 'svelte';
  import Button from '../components/Button.svelte';
  import Popover from '../components/Popover.svelte';
  import { clearSessionCache } from '../sessions/catalog.svelte';
  import { beginForceShutdownAll, finishForceShutdownAll } from '../session/launch.svelte';
  type Action = 'force-stop' | 'delete-history';
  interface Result { ok: boolean; confirmed?: string[]; deleted?: number; failed?: { id?: string; message: string }[]; }
  let confirmation = $state<Action | null>(null), busy = $state<Action | null>(null);
  let stopAnchor = $state<HTMLButtonElement>(), deleteAnchor = $state<HTMLButtonElement>();
  let cancelAnchor = $state<HTMLButtonElement>();
  let message = $state(''), error = $state(false);
  let resultOpen = $state(false), resultAction = $state<Action>('force-stop');
  const anchor = $derived(confirmation === 'force-stop' ? stopAnchor : deleteAnchor);
  async function show(action: Action) { confirmation = action; await tick(); cancelAnchor?.focus({ preventScroll: true }); }
  function dismiss() { const target = anchor; confirmation = null; target?.focus({ preventScroll: true }); }
  async function perform(action: Action) {
    if (busy) return;
    confirmation = null; busy = action; message = 'Starting…'; error = false; resultAction = action; resultOpen = true;
    let result: Result | undefined;
    if (action === 'force-stop') beginForceShutdownAll();
    try {
      const events = new Channel<{ type: string; action?: Action; phase?: string; line?: string; result?: Result }>();
      events.onmessage = event => {
        if (event.type === 'status' && event.phase) message = event.phase;
        if (event.type === 'finished' && event.action === action) result = event.result;
      };
      await invoke('sensitive_settings', { action, events });
      if (!result) throw new Error('Operation ended without a confirmed result. Refresh before retrying.');
      error = !result.ok;
      const summary = action === 'force-stop' ? `${result.confirmed?.length ?? 0} rigs shut down` : `${result.deleted ?? 0} session histories deleted`;
      message = [summary, ...(result.failed ?? []).map(failure => `${failure.id ? failure.id + ': ' : ''}${failure.message}`)].join('\n');
      if (action === 'delete-history') clearSessionCache();
    } catch (failure) { error = true; message = String(failure); }
    finally {
      if (action === 'force-stop') await finishForceShutdownAll(result?.confirmed ?? [], !!result?.ok);
      busy = null;
      await tick(); (action === 'force-stop' ? stopAnchor : deleteAnchor)?.focus({ preventScroll: true });
    }
  }
</script>
<section class="settings-box" aria-labelledby="sensitive-heading">
  <header><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 10 18H2zM12 9v5M12 17h.01"/></svg><h2 id="sensitive-heading">Sensitive settings</h2></header>
  <div class="action"><div><strong title="Force shutdown all running sessions">Force shutdown all running sessions</strong><p title="Destroy running and retained Vastgame rigs without backing up saves.">Destroy running and retained Vastgame rigs without backing up saves.</p></div><Button size="small" tone="red" bind:element={stopAnchor} disabled={!!busy} onclick={() => void show('force-stop')}>{busy === 'force-stop' ? 'Shutting down…' : 'Force shutdown all'}</Button></div>
  <div class="action"><div><strong title="Delete all session history">Delete all session history</strong><p title="Permanently erase session records and archived logs.">Permanently erase session records and archived logs.</p></div><Button size="small" tone="red" bind:element={deleteAnchor} disabled={!!busy} onclick={() => void show('delete-history')}>{busy === 'delete-history' ? 'Deleting…' : 'Delete history'}</Button></div>
</section>
<Popover open={resultOpen && !confirmation} anchor={resultAction === 'force-stop' ? stopAnchor : deleteAnchor} persistent label="Sensitive action result" onclose={() => resultOpen = false}>
  <p class="result" class:error role={error ? 'alert' : 'status'}>{message}</p>
</Popover>
<Popover open={!!confirmation} {anchor} persistent label="Confirm sensitive action" onclose={dismiss}>
  <p>{confirmation === 'force-stop' ? 'Destroy every running or retained Vastgame rig now? Unbacked saves may be lost.' : 'Permanently delete all session history and archived logs? This cannot be undone. Active rig controls and game saves remain.'}</p>
  <div class="confirm"><Button variant="plain" bind:element={cancelAnchor} onclick={dismiss}>Cancel</Button><Button tone="red" onclick={() => confirmation && void perform(confirmation)}>Confirm</Button></div>
</Popover>
<style>
  .action { display: flex; align-items: center; gap: 8px; min-height: 32px; padding: var(--sensitive-action-padding) calc(var(--page-margin) / 2); border-radius: 16px; background: var(--surface); }
  .action > div { flex: 1; min-width: 0; }
  strong { display: block; color: var(--session-failed); font-size: 12px; line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  header { color: var(--session-failed); }
  .action p { margin: 2px 0 0; font-size: 11px; color: var(--text-muted); line-height: 1.2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .result { white-space: pre-wrap; overflow-wrap: anywhere; }
  .result.error { color: var(--log-error); }
  .confirm { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
  @container (max-width: 380px) { .action :global(.face) { padding-inline: 8px; } }
</style>
