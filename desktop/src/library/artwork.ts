import { invoke } from '@tauri-apps/api/core';
import { applyIdentity } from './catalog.svelte';
const pending = new Map<string, Promise<string | null>>();
const cached = new Map<string, string>();
const queue: (() => void)[] = [];
let active = 0, characters = 0;
export function artwork(gameId: string, kind: 'cover' | 'banner'): Promise<string | null> {
  const key = `${gameId}-${kind}`;
  const image = cached.get(key);
  if (image) { cached.delete(key); cached.set(key, image); return Promise.resolve(image); }
  if (!pending.has(key)) {
    const request = new Promise<string | null>(resolve => {
      const run = () => {
        active++;
        invoke<{ image: string | null; identity?: { name: string; steam_appid: number | null } }>('game_artwork', { gameId, kind })
          .then(result => {
            applyIdentity(gameId, result.identity);
            if (result.image) {
              cached.set(key, result.image); characters += result.image.length;
              while (characters > 8 * 1024 * 1024 || cached.size > 32) {
                const oldest = cached.keys().next().value!;
                characters -= cached.get(oldest)!.length; cached.delete(oldest);
              }
            }
            resolve(result.image);
          }).catch(() => resolve(null))
          .finally(() => { pending.delete(key); active--; queue.shift()?.(); });
      };
      if (active < 2) run(); else queue.push(run);
    });
    pending.set(key, request);
  }
  return pending.get(key)!;
}
