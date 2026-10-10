<script lang="ts">
  import { onMount } from 'svelte';
  import { account, refreshBalance } from './balance.svelte';

  const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const amount = $derived(account.usd === null ? '$—' : currency.format(account.usd));
  const label = $derived(account.error || (account.usd === null ? 'Loading account balance' : `Vast account balance: ${amount}`));
  onMount(() => { void refreshBalance(); });
</script>

<svelte:window onfocus={() => void refreshBalance()}/>

<div class="balance" role="status" aria-label={label} aria-busy={account.loading} title={account.error ? `${amount} · ${account.error}` : label}>
  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 8V6a2 2 0 0 0-2-2H6a3 3 0 0 0 0 6h14v10H6a3 3 0 0 1-3-3V7 M20 12h-4a2 2 0 0 0 0 4h4"/><circle cx="16" cy="14" r=".5"/></svg>
  <span class:known={account.usd !== null} class:low={account.usd !== null && account.usd < 0.5}>{amount}</span>
</div>

<style>
  .balance { display: flex; align-items: center; justify-content: center; gap: 8px; flex-shrink: 0; height: var(--button-size); padding: 0 14px; border-radius: 99px; background: var(--surface-dark); color: var(--text); font-size: 12px; }
  svg { width: 18px; height: 18px; flex-shrink: 0; }
  span { font-weight: 600; font-variant-numeric: tabular-nums; white-space: nowrap; color: var(--text-muted); }
  span.known { color: var(--price); }
  span.low { color: var(--balance-low); }
</style>
