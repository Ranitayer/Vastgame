import { invoke } from '@tauri-apps/api/core';
import { library } from '../library/catalog.svelte';
import type { HostCatalog } from './types';

export const hosts = $state({ catalog: null as HostCatalog | null, gameId: null as string | null, loading: false, error: '' });
let requested: string | null = null;
let revision = 0;
let queued: { game: string; revision: number } | null = null;
let worker: Promise<void> | undefined;
export function invalidateHosts() { requested = null; revision++; queued = null; }

export function ensureHosts(game = '') { if (requested !== game) return refreshHosts(game); return worker; }
export function refreshHosts(game = ''): Promise<void> {
  requested = game;
  queued = { game, revision: ++revision };
  hosts.loading = true; hosts.error = '';
  if (worker) return worker;
  worker = Promise.resolve().then(async () => {
    while (queued) {
      const request = queued; queued = null;
      try {
        const chosen = library.catalog?.games.find(item => item.id === request.game);
        if (chosen && (!chosen.packaged || chosen.required_disk_gb === null)) {
          hosts.catalog = { offers: [], disk_gb: 60, updated: Date.now() / 1000 };
          hosts.gameId = request.game;
          hosts.error = 'Package this game first; its safe storage requirement is unavailable';
          continue;
        }
        const result = await invoke<HostCatalog>('browse_hosts', { gameId: request.game || null });
        if (request.revision !== revision) continue;
        hosts.catalog = result; hosts.gameId = request.game;
      } catch (error) { if (request.revision === revision) { hosts.error = String(error); hosts.catalog = null; } }
    }
  }).finally(() => {
    worker = undefined;
    if (queued) return refreshHosts(queued.game);
    hosts.loading = false;
  });
  return worker;
}
