import { invoke } from '@tauri-apps/api/core';

export const account = $state({ usd: null as number | null, loading: false, error: '' });
let request: Promise<void> | undefined;
let lastAttempt = 0;

export function refreshBalance(force = false): Promise<void> {
  if (request) return request;
  if (!force && Date.now() - lastAttempt < 60_000) return Promise.resolve();
  lastAttempt = Date.now();
  account.loading = true;
  request = invoke<{ balance: { usd: number } }>('account_balance').then(result => {
    if (typeof result.balance?.usd !== 'number' || !Number.isFinite(result.balance.usd)) {
      throw new Error('Invalid account balance');
    }
    account.usd = result.balance.usd;
    account.error = '';
  }).catch(() => {
    account.error = account.usd === null ? 'Balance unavailable. Refresh to retry.' : 'Could not refresh. Showing last known balance.';
  }).finally(() => { account.loading = false; request = undefined; });
  return request;
}
