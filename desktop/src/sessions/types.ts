import { launch } from '../session/launch.svelte';
export interface SessionRecord {
  id: string; job_id?: string; game_id?: string; game_name?: string; instance_id?: string | null;
  started_at?: number | null; created_at?: number | null; ended_at?: number | null;
  duration_ms?: number | null; played_ms?: number | null; game_active_since?: number | null;
  summary_at?: number;
  outcome: string; phase?: string; last_error?: string; game_running?: boolean;
  failed?: boolean; last_attempt_success?: boolean; force_shutdown?: boolean;
  state?: SessionState; operation_pending?: boolean;
  rig?: { machine_id?: number; gpu_name?: string; gpu_ram?: number; geolocation?: string; cpu_name?: string; inet_down?: number; inet_up?: number };
  logs_complete?: boolean;
  stage_times?: Record<string, number>;
  billing?: { status: string; reported_usd?: string; error?: string; observed_at?: number };
  estimated_compute_storage_usd?: string | null;
}
export type SessionState = 'Starting' | 'Running' | 'Failed' | 'Retained' | 'Shutdown';
export interface SessionQuery { days: number; status: string; order: string; }
export interface SessionCatalog { sessions: SessionRecord[]; total: number; skipped: number; }
export function sessionState(record: SessionRecord): SessionState {
  const closedState = record.failed || (record.last_attempt_success === false && !record.force_shutdown) || record.outcome === 'no_rental' ? 'Failed' : 'Shutdown';
  if (record.ended_at || record.outcome === 'stopped') return closedState;
  if (record.job_id === launch.jobId) {
    if (launch.status === 'stopped') return closedState;
    if (launch.status === 'starting' || launch.connecting) return 'Starting';
    if (launch.status === 'error') return 'Failed';
    if (launch.instanceId) return launch.phase === 'Game exited' ? 'Retained' : launch.gameRunning || launch.busy ? 'Running' : 'Retained';
  }
  if (record.state) return record.state;
  if (record.operation_pending || ['preparing', 'creating'].includes(record.outcome)) return 'Starting';
  if (record.outcome === 'retained') return 'Retained';
  if (record.outcome === 'active') return record.game_running === false ? 'Retained' : 'Running';
  return 'Failed';
}
export function sessionAction(record: SessionRecord) {
  const state = sessionState(record);
  if (state === 'Running') return { label: 'Shutdown', tone: 'red' } as const;
  if (state === 'Starting') return record.instance_id || (record.job_id === launch.jobId && launch.instanceId) ? { label: 'Shutdown', tone: 'red' } as const : { label: 'Starting', tone: 'blue' } as const;
  const running = record.job_id === launch.jobId ? launch.gameRunning : record.game_running;
  if (state === 'Retained' && running) return { label: 'Resume', tone: 'green' } as const;
  return { label: state === 'Retained' ? 'Reconnect' : 'Connect', tone: 'blue' } as const;
}
export function duration(milliseconds: number | null | undefined) {
  if (milliseconds == null) return '—';
  const minutes = Math.max(0, Math.floor(milliseconds / 60000));
  return minutes < 60 ? `${minutes}m` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}
const dollars = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2 });
export function sessionCost(record: SessionRecord) {
  const billing = record.billing;
  const reported = billing?.reported_usd;
  const value = Number(reported ?? record.estimated_compute_storage_usd ?? NaN);
  if (!Number.isFinite(value)) return { text: record.instance_id ? 'Cost pending' : 'Cost unknown', title: billing?.error || (record.instance_id ? 'Provider charges are not available yet. Refresh to request them.' : 'This older record has no exact provider instance ID; its charges cannot be attributed safely.') };
  return reported !== undefined ? {
    text: `${dollars.format(value)}${billing?.status === 'stale' ? ' · stale' : ''}`,
    title: 'Vast-reported session charges, including available adjustments. Final settlement may arrive later.',
  } : { text: dollars.format(value), title: 'Estimated compute and storage cost. Network charges, adjustments and refunds are not included.' };
}
