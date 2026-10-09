export interface StartupStage {
  id: 'boot' | 'game' | 'runtime' | 'saves' | 'start'; name: string;
  state: 'pending' | 'running' | 'done' | 'error'; action?: string;
  bytes?: number; total?: number; percent?: number; speed?: number; eta?: number; measured_at?: number;
}
export interface StartupProgress { active: StartupStage['id']; stages: StartupStage[]; }
