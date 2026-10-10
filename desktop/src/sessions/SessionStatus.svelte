<script lang="ts">
  import { sessionState, type SessionRecord } from './types';
  let { record, dot = true }: { record: SessionRecord; dot?: boolean } = $props();
</script>
<span class="status" data-state={sessionState(record)} title={record.last_error || record.phase || 'Last recorded state'}>{#if dot}<i aria-hidden="true"></i>{/if}{sessionState(record)}</span>
<style>
  .status { display: inline-flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-muted); }
  i { width: 7px; height: 7px; flex-shrink: 0; border-radius: 50%; background: currentColor; }
  .status[data-state='Running'] { color: var(--price); }
  .status[data-state='Failed'] { color: var(--session-failed); }
  .status[data-state='Retained'], .status[data-state='Starting'] { color: var(--log-info); }
</style>
