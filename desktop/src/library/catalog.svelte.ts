import { invoke } from '@tauri-apps/api/core';
import type { LibraryCatalog } from './types';
export const library = $state({ catalog: null as LibraryCatalog | null, loading: false, error: '', revision: 0 });
let pending: Promise<void> | undefined;
export function refreshLibrary() {
  if (pending) return pending;
  library.loading = true; library.error = '';
  pending = invoke<LibraryCatalog>('browse_library').then(catalog => { library.catalog = catalog; library.revision++; })
    .catch(error => { library.error = String(error); })
    .finally(() => { library.loading = false; pending = undefined; });
  return pending;
}
export function ensureLibrary() { if (!library.catalog) return refreshLibrary(); }
export function applyIdentity(id: string, identity?: { name: string; steam_appid: number | null }) {
  const game = library.catalog?.games.find(game => game.id === id);
  if (!game || !identity?.steam_appid || !Number.isInteger(identity.steam_appid) || typeof identity.name !== 'string') return;
  game.name = identity.name;
  game.steam_appid = identity.steam_appid;
}
