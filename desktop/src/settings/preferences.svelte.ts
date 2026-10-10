import { invoke } from '@tauri-apps/api/core';
import { invalidateHosts } from '../hosts/catalog.svelte';

export interface StreamPreferences { video_codec: string; fps: number | 'native'; resolution: string; bitrate_mbps: number | null; video_decoder?: string; display_mode?: string; moonlight_options?: Record<string, boolean | string | number>; }
export interface HostPreferences { country: string; preferred_gpu: string; spending_limit_usd: number; verified_only: boolean; min_download_mbps: number; min_upload_mbps: number; min_vram_gb: number; min_ram_gb: number; }
export interface Preferences { stream: StreamPreferences; hosts: HostPreferences; }
interface Response { settings: Preferences; countries: { value: string; label: string }[]; error?: { message: string }; }
export const preferences = $state({ data: null as Preferences | null, countries: [] as Response['countries'], loading: false, saving: false, error: '', revision: 0 });
let worker: Promise<void> | undefined;

function accept(result: Response) {
  if (result.error) throw new Error(result.error.message);
  if (!result.settings || !Array.isArray(result.countries)) throw new Error('Invalid settings response. Update the backend.');
  preferences.data = result.settings; preferences.countries = result.countries;
}
export function ensurePreferences(): Promise<void> {
  if (worker) return worker;
  if (preferences.data) return Promise.resolve();
  preferences.loading = true; preferences.error = '';
  worker = invoke<Response>('read_settings').then(accept).catch(error => { preferences.error = String(error); })
    .finally(() => { preferences.loading = false; worker = undefined; });
  return worker;
}
export async function savePreferences(patch: Partial<Preferences>) {
  if (preferences.saving) throw new Error('A settings save is already active.');
  preferences.saving = true;
  try {
    accept(await invoke<Response>('save_settings', { patch }));
    invalidateHosts(); preferences.revision++;
  } finally { preferences.saving = false; }
}

export async function resetPreferences() {
  if (preferences.saving) throw new Error('A settings save is already active.');
  preferences.saving = true;
  try {
    if (worker) await worker;
    accept(await invoke<Response>('reset_settings'));
    invalidateHosts(); preferences.revision++;
  } finally { preferences.saving = false; }
}
