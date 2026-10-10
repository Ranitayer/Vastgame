import { invoke } from '@tauri-apps/api/core';
import type { SessionCatalog, SessionQuery } from './types';
export const history = $state({ catalog: null as SessionCatalog | null, loading: false, error: '', erased: 0 });
let revision = 0;
let catalogKey = '';
let queued: { query: SessionQuery; more: boolean; billing: boolean; revision: number } | null = null;
let worker: Promise<void> | undefined;
export function clearSessionCache() { revision++; queued = null; catalogKey = ''; history.catalog = null; history.error = ''; history.erased++; }
export function refreshSessions(query: SessionQuery, more = false, billing = false): Promise<void> {
  queued = { query, more, billing, revision: ++revision };
  history.loading = true; history.error = '';
  if (worker) return worker;
  worker = Promise.resolve().then(async () => {
    while (queued) {
      const request = queued; queued = null;
      const key = JSON.stringify(request.query);
      const append = request.more && key === catalogKey;
      const offset = append ? history.catalog?.sessions.length ?? 0 : 0;
      try {
        const catalog = await invoke<SessionCatalog>('browse_sessions', { offset, refreshBilling: request.billing, ...request.query });
        if (request.revision !== revision) continue;
        const records = append ? [...history.catalog?.sessions ?? [], ...catalog.sessions] : catalog.sessions;
        history.catalog = { ...catalog, sessions: [...new Map(records.map(record => [record.id, record])).values()] };
        catalogKey = key;
      } catch (error) { if (request.revision === revision) history.error = String(error); }
    }
  }).finally(() => {
    worker = undefined;
    if (queued) return refreshSessions(queued.query, queued.more, queued.billing);
    history.loading = false;
  });
  return worker;
}
