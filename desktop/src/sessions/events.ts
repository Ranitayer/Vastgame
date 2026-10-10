import { phaseLabel } from '../session/progress';
import type { LogEntry } from '../session/logs';
import type { SessionRecord } from './types';
import type { SessionEvent } from './archive';

export function sessionEvents(record: SessionRecord, transitions?: SessionEvent[]): LogEntry[] {
  const events = (transitions ?? Object.entries(record.stage_times ?? {}).map(([message, time]) => ({ message, time })))
    .filter((entry): entry is SessionEvent & { time: number } => entry.time !== null && Number.isFinite(entry.time) && entry.time > 0)
    .map(({ message: phase, time }) => ({ time, message: /failed|failure|error/i.test(phase) || phase.length > 64 ? phaseLabel(phase, 'Rig activity') : phase }));
  if (record.started_at) events.push({ time: record.started_at, message: 'Session started' });
  if (record.ended_at) events.push({ time: record.ended_at, message: record.outcome === 'no_rental' ? 'Launch failed' : 'Rig shut down' });
  events.sort((left, right) => left.time - right.time);
  return events.filter((entry, index) => index === 0 || entry.message !== events[index - 1].message).map(entry => ({
    message: entry.message,
    level: entry.message === 'Launch failed' ? 'error' : ['Game running', 'Rig shut down'].includes(entry.message) ? 'success' : 'info',
  }));
}
