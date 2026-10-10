export interface StartupStage {
  id: 'boot' | 'game' | 'runtime' | 'saves' | 'start'; name: string;
  state: 'pending' | 'running' | 'done' | 'error'; action?: string;
  bytes?: number; total?: number; percent?: number; speed?: number; eta?: number; measured_at?: number;
}
export interface StartupProgress { active: StartupStage['id']; stages: StartupStage[]; }

export function phaseLabel(value: string, fallback = 'Game ready'): string {
  const phase = value.toLowerCase();
  if (phase === 'game running') return 'Game running';
  if (phase === 'game exited') return 'Game exited';
  if (phase === 'rig shut down') return 'Rig shut down';
  if (/failed|failure|error/.test(phase)) return 'Launch failed';
  if (phase.includes('closing game')) return 'Closing game';
  if (phase.includes('backup') || phase.includes('saving') || phase.includes('backing up')) return 'Saving game';
  if (phase.includes('shutting') || phase.includes('shut down')) return 'Stopping rig';
  if (phase.includes('checking') || phase.includes('quote')) return 'Checking rig';
  if (phase.includes('restor') && phase.includes('game') && !phase.includes('saves')) return 'Restoring game';
  if (phase.includes('restor')) return 'Restoring saves';
  if (phase.includes('boot')) return 'Booting rig';
  if (phase.includes('allocat') || phase.includes('creating')) return 'Creating rig';
  if (phase.includes('connecting') || phase.includes('tailscale')) return 'Connecting rig';
  if (phase.includes('runtime') || phase.includes('image') || phase.includes('server')) return 'Preparing rig';
  if (phase.includes('moonlight')) return 'Opening stream';
  if (phase.includes('starting game')) return 'Starting game';
  return fallback;
}
