import { invoke } from '@tauri-apps/api/core';
export interface SteamDetails {
  description: string;
  reviews: { total: number; positive: number; sentiment: string } | null;
}
const cached = new Map<number, { expires: number; request: Promise<SteamDetails | null> }>();
export function gameDetails(appid: number): Promise<SteamDetails | null> {
  const entry = cached.get(appid);
  if (entry && entry.expires > Date.now()) return entry.request;
  const request = invoke<{ details: SteamDetails | null }>('game_details', { steamAppid: appid })
    .then(result => {
      if (!result.details?.description || !result.details.reviews) cached.delete(appid);
      return result.details;
    }).catch(() => { cached.delete(appid); return null; });
  cached.delete(appid);
  cached.set(appid, { expires: Date.now() + 86400000, request });
  while (cached.size > 128) cached.delete(cached.keys().next().value!);
  return request;
}
