<script lang="ts">
  import Button from './Button.svelte';
  let { search = $bindable(''), label, placeholder, loading, onrefresh }: {
    search?: string; label: string; placeholder: string; loading: boolean; onrefresh: () => void;
  } = $props();
</script>
<div class="search-group">
  <label><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/></svg><input type="search" {placeholder} aria-label={`Search ${label}`} bind:value={search}/></label>
  <Button icon disabled={loading} aria-label={loading ? `Refreshing ${label}` : `Refresh ${label}`} title={`Refresh ${label}`} onclick={onrefresh}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5 M20 12a8 8 0 1 0-2 5"/></svg></Button>
</div>
<style>
  .search-group { display: flex; flex: 0 1 calc(240px + var(--button-size) + 8px); width: calc(240px + var(--button-size) + 8px); min-width: 0; gap: 8px; }
  label { display: flex; flex: 0 1 240px; width: 240px; min-width: 0; align-items: center; gap: 12px; padding: 0 16px; height: var(--button-size); border-radius: 16px; background: var(--surface-hover); color: var(--text-muted); }
  label:focus-within { outline: 2px solid var(--focus); outline-offset: -2px; }
  input { width: 100%; min-width: 0; padding: 0; border: 0; outline: none; font: inherit; font-size: 13px; color: var(--text); background: transparent; }
  input::placeholder { color: var(--text-muted); }
</style>
