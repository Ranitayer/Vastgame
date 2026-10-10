import { Channel, invoke } from '@tauri-apps/api/core';
import type { Game } from '../library/types';
import type { Host } from '../hosts/types';
import { phaseLabel, type StartupProgress } from './progress';
import { formatLog, appendLogs, type LogEntry } from './logs';
export interface LaunchError { code: string; message: string; required?: number; available?: number; current?: number; approved?: number; }
interface Quote { offer_id: number; machine_id: number | null; price: number; disk_gb: number; }
export interface RestoredSession {
  jobId: string; gameId: string; gameName: string; instanceId: string | null; startedAt: number; endedAt: number;
  phase: string; status: string; shutdownRequested: boolean; gameRunning: boolean; stateFresh: boolean; observedAt: number; progress: StartupProgress | null;
}
interface Event { progress?: StartupProgress; game_running?: boolean; error?: LaunchError; type: string; line?: string; phase?: string; ok?: boolean; instance_id?: string | null; }
export const launch = $state({ jobId: '', gameId: '', gameName: '', rig: null as Host | null, startedAt: 0, endedAt: 0, gameRunning: false, phase: '', busy: false, connecting: false, stopping: false, shutdownRequested: false, forcing: false, instanceId: null as string | null, status: 'idle', stateFresh: false, observedAt: 0, unresolved: false, restoring: true, progress: null as StartupProgress | null, error: null as LaunchError | null, logs: [] as LogEntry[] });
let restoration: Promise<void> | undefined;
let restored = false;
let restoreError = '';
let lastRefresh = 0;
let pendingQuote: { key: string; quote: Quote } | null = null;
let queue: LogEntry[] = [];
let launchCanceled = false;
let shutdownGeneration = 0;
let timer: ReturnType<typeof setTimeout> | undefined;
function log(line: string) {
  const entry = formatLog(line);
  if (!entry) return;
  queue.push(entry);
  if (queue.length > 500) queue.shift();
  if (timer) return;
  timer = setTimeout(() => { launch.logs = appendLogs(launch.logs, queue); queue = []; timer = undefined; }, 100);
}
function receive(event: Event, job: string, shutdown = false, logsOnly = false) {
  if (launch.jobId !== job) return;
  if (event.type === 'log' && event.line) log(event.line);
  if (logsOnly || (!shutdown && launchCanceled)) return;
  if (event.progress) {
    if (event.progress.active !== launch.progress?.active) {
      const stage = event.progress.stages.find(item => item.id === event.progress?.active);
      if (stage) log(`Stage: ${stage.name}`);
    }
    launch.progress = event.progress;
  }
  if (event.game_running !== undefined) launch.gameRunning = event.game_running;
  if (event.type === 'error' && event.error) { launch.unresolved = event.error.code === 'CREATION_UNCONFIRMED'; launch.error = event.error; launch.phase = event.error.message; }
  if (event.type === 'instance') launch.instanceId = event.instance_id ?? null;
  if (event.type === 'status' && event.phase) { if (event.phase !== launch.phase) log(`Stage: ${event.phase}`); launch.phase = event.phase; if (event.phase === 'Game running') { launch.gameRunning = true; launch.stateFresh = true; launch.observedAt = Date.now(); } }
  if (event.type === 'finished') {
    launch.busy = false; launch.stopping = false;
    launch.phase = event.phase || 'Operation ended';
    if (event.instance_id !== undefined) launch.instanceId = event.instance_id;
    launch.status = event.ok ? shutdown ? 'stopped' : 'ready' : 'error';
    if (!launch.instanceId && !launch.unresolved && !launch.endedAt) launch.endedAt = Date.now();
    if (shutdown && event.ok) launch.gameRunning = false;
  }
}
function events(job: string, shutdown = false, logsOnly = false) {
  const channel = new Channel<Event>();
  channel.onmessage = event => receive(event, job, shutdown, logsOnly);
  return channel;
}
export async function play(game: Game, rig: Host | null, maxPrice?: number): Promise<string> {
  const startedAt = Date.now();
  await restoreLaunch();
  if (restoreError) return restoreError;
  if (launch.unresolved) return 'Rental result unknown. Refresh status before trying again';
  if (launch.instanceId) return connect();
  if (!rig) return 'Choose rig first';
  if (!game.packaged || game.required_disk_gb == null) return 'Package this game first';
  if (launch.busy || launch.connecting || launch.stopping) return 'Another operation is active – check Logs';
  if (timer) clearTimeout(timer);
  timer = undefined; queue = []; launchCanceled = false;
  const generation = shutdownGeneration;
  const job = crypto.randomUUID().replaceAll('-', '');
  const key = `${game.id}:${rig.id}:${game.required_disk_gb}`;
  const approved = maxPrice ?? Math.max(rig.dph_total, pendingQuote?.key === key ? pendingQuote.quote.price : 0);
  Object.assign(launch, { jobId: job, gameId: game.id, gameName: game.name, rig, startedAt, endedAt: 0, gameRunning: false, phase: 'Refreshing game quote', busy: true, stopping: false, shutdownRequested: false, forcing: false, instanceId: null, status: 'starting', error: null, logs: [], progress: null, stateFresh: false, unresolved: false });
  try {
    const result = await invoke<{ quote?: Quote; error?: LaunchError }>('quote_game', { gameId: game.id, offerId: rig.id, machineId: rig.machine_id ?? 0 });
    if (launch.jobId !== job || launchCanceled || generation !== shutdownGeneration) return '';
    if (result.error) {
      launch.error = result.error; launch.phase = result.error.message; launch.busy = false; launch.status = 'error'; launch.endedAt = Date.now();
      log(`[${result.error.code}] ${result.error.message}`);
      return result.error.message;
    }
    const quote = result.quote;
    if (!quote) throw new Error('Provider quote missing; no VM rented');
    log(`Game quote: $${quote.price.toFixed(4)}/h with ${quote.disk_gb} GB allocated`);
    if (maxPrice !== undefined && quote.price > maxPrice + 1e-9) {
      const message = 'Previous rig price increased beyond 10%. Choose a rig on Home';
      launch.error = { code: 'HISTORY_PRICE_CHANGED', message, current: quote.price, approved: maxPrice };
      launch.phase = message; launch.busy = false; launch.status = 'error'; launch.endedAt = Date.now(); log(`[HISTORY_PRICE_CHANGED] ${message}`);
      return message;
    }
    if (quote.price > approved + 1e-9) {
      pendingQuote = { key, quote };
      const message = `Price changed: $${approved.toFixed(4)}/h → $${quote.price.toFixed(4)}/h. Click Play again to approve`;
      launch.error = { code: 'PRICE_CONFIRMATION', message, approved, current: quote.price };
      launch.phase = message; launch.busy = false; launch.status = 'quote'; launch.endedAt = Date.now(); log(`[PRICE_CONFIRMATION] ${message}`);
      return message;
    }
    pendingQuote = null;
    launch.phase = 'Checking selected rig';
    void invoke('launch_game', { gameId: game.id, offerId: rig.id, machineId: rig.machine_id ?? 0, maxPrice: quote.price, jobId: job, startedAt, events: events(job) })
      .catch(error => { if (launch.jobId === job && !launchCanceled) { log(`[BACKEND_FAILED] ${String(error)}`); launch.busy = false; launch.status = 'error'; launch.unresolved = true; launch.error = { code: 'BACKEND_FAILED', message: String(error) }; launch.phase = String(error); void restoreLaunch(true); } });
    return '';
  } catch (error) {
    if (launch.jobId !== job || launchCanceled || generation !== shutdownGeneration) return '';
    const message = String(error);
    launch.error = { code: 'QUOTE_FAILED', message }; launch.phase = message; launch.busy = false; launch.status = 'error'; launch.endedAt = Date.now(); log(`[QUOTE_FAILED] ${message}`);
    return message;
  }
}
export async function connect(): Promise<string> {
  if (!launch.instanceId) return 'No running rig to connect';
  if (launch.busy || launch.connecting || launch.stopping) return 'Another operation is active – check Logs';
  const job = launch.jobId;
  const generation = shutdownGeneration;
  let message = '';
  const channel = new Channel<Event>();
  channel.onmessage = event => {
    if (launch.jobId !== job) return;
    if (generation !== shutdownGeneration) {
      if (event.type === 'log' && event.line) log(event.line);
      return;
    }
    receive(event, job);
    if (event.type === 'error') message = event.error?.message || 'Connection failed – check Logs';
    if (event.type === 'finished' && !event.ok) message ||= event.phase || 'Connection failed – check Logs';
  };
  launchCanceled = false;
  launch.connecting = true; launch.busy = true; launch.status = 'starting'; launch.error = null; launch.progress = null; launch.phase = 'Resuming rig';
  try { await invoke('connect_game', { jobId: job, events: channel }); }
  catch (error) {
    if (launch.jobId === job && generation === shutdownGeneration) {
      message = String(error); log(`[CONNECT_FAILED] ${message}`); launch.status = 'error'; launch.phase = 'Connection failed; VM retained';
    }
  }
  finally { if (launch.jobId === job && generation === shutdownGeneration) { launch.connecting = false; launch.busy = false; } }
  return generation === shutdownGeneration ? message : '';
}
export function shutdown() {
  // Repeated clicks keep the existing force request; never submit duplicate destruction.
  if (!launch.instanceId || launch.forcing) return;
  const job = launch.jobId;
  const force = launch.shutdownRequested || launch.busy || launch.connecting;
  const generation = ++shutdownGeneration;
  launchCanceled = true;
  launch.shutdownRequested = true; launch.forcing = force;
  launch.connecting = false; launch.stopping = true; launch.busy = true; launch.status = 'stopping'; launch.error = null;
  launch.phase = force ? 'Force stopping rig' : 'Checking rig';
  const channel = new Channel<Event>();
  channel.onmessage = event => {
    if (generation !== shutdownGeneration) {
      if (launch.jobId === job && event.type === 'log' && event.line) log(event.line);
      return;
    }
    receive(event, job, true);
  };
  void invoke('shutdown_game', { jobId: job, force, events: channel })
    .catch(error => {
      if (generation !== shutdownGeneration || launch.jobId !== job) return;
      log(`[SHUTDOWN_FAILED] ${String(error)}`); launch.busy = false; launch.stopping = false;
      launch.status = 'error'; launch.phase = 'Shutdown failed; VM retained';
    }).finally(() => { if (generation === shutdownGeneration && launch.jobId === job) launch.forcing = false; });
}

export function restoreLaunch(refresh = false): Promise<void> {
  if (restoration) return restoration;
  if (restored && !refresh) return Promise.resolve();
  if (refresh && (launch.busy || launch.connecting || launch.stopping)) return Promise.resolve();
  const expected = launch.jobId;
  launch.restoring = true;
  restoration = (async () => {
    try {
      const result = await invoke<{ error?: LaunchError; session?: RestoredSession | null }>('current_launch', { jobId: expected || null });
      if (result.error) throw new Error(result.error.message);
      if (launch.jobId !== expected || launch.stopping || (expected && launch.status === 'stopped')) return;
      restoreError = '';
      if (result.session) {
        const rig = launch.jobId === result.session.jobId ? launch.rig : null;
        useSession(result.session, rig);
      } else if (expected) {
        const failed = launch.status === 'error' || launch.status === 'quote';
        Object.assign(launch, { jobId: failed ? expected : '', instanceId: null, gameRunning: false, busy: false, stopping: false, unresolved: false, status: failed ? 'error' : 'stopped' });
        if (launch.startedAt && !launch.endedAt) launch.endedAt = Date.now();
        pendingQuote = null;
      }
    } catch (error) { restoreError = String(error); log(`[SESSION_LOOKUP_FAILED] ${restoreError}`); }
    finally { restored = true; launch.restoring = false; lastRefresh = Date.now(); restoration = undefined; }
  })();
  return restoration;
}

export function useSession(session: RestoredSession | null, rig: Host | null = null) {
  restoreError = ''; restored = true;
  if (!session) {
    launchCanceled = true;
    Object.assign(launch, { instanceId: null, gameRunning: false, busy: false, connecting: false, stopping: false, forcing: false, unresolved: false, status: 'stopped' });
    if (launch.startedAt && !launch.endedAt) launch.endedAt = Date.now();
    return;
  }
  Object.assign(launch, session, { rig, busy: session.status === 'starting', connecting: false, stopping: false, forcing: false, error: null, unresolved: !session.instanceId });
  launchCanceled = false;
  const job = launch.jobId;
  if (timer) clearTimeout(timer); timer = undefined; queue = []; launch.logs = [];
  void invoke('follow_launch', { jobId: job, events: events(job, false, session.status !== 'starting') })
    .catch(error => { if (launch.jobId === job) log(`[LOG_FAILED] ${String(error)}`); });
}
export function reconcileLaunch() {
  if ((launch.jobId || restoreError) && Date.now() - lastRefresh > 1000) return restoreLaunch(true);
  return Promise.resolve();
}

export function beginForceShutdownAll() {
  launchCanceled = true; shutdownGeneration++;
  Object.assign(launch, { busy: true, stopping: true, forcing: true, connecting: false,
    shutdownRequested: true, status: 'stopping', phase: 'Force stopping rigs' });
}

export async function finishForceShutdownAll(confirmed: string[], ok: boolean) {
  const stopped = launch.instanceId ? confirmed.includes(launch.instanceId) : ok;
  Object.assign(launch, { busy: false, stopping: false, forcing: false, connecting: false });
  if (stopped) useSession(null);
  else Object.assign(launch, { status: 'error', phase: 'Shutdown unconfirmed', unresolved: true });
  await restoreLaunch(true);
}

export function compactPhase(): string {
  if (launch.gameRunning && launch.status === 'ready') return 'Last running';
  if (launch.status === 'quote') return 'Confirm price';
  if (launch.status === 'error') return launch.instanceId ? 'Rig retained' : 'Launch failed';
  const stage = launch.progress?.active;
  if (launch.status === 'starting' && stage === 'game') return 'Restoring game';
  if (launch.status === 'starting' && stage === 'saves') return 'Restoring saves';
  return phaseLabel(launch.phase, launch.busy ? 'Starting rig' : 'Game ready');
}
