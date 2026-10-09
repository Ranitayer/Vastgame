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
