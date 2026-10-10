import { invoke } from '@tauri-apps/api/core';
import { copyText } from '../components/clipboard';
import type { SessionRecord } from './types';
import { sessionEvents } from './events';
export interface SessionEvent { time: number | null; message: string; }
export interface LogPage { session: SessionRecord; entries: SessionEvent[]; next_cursor: number | null; logs_complete: boolean; events_complete?: boolean; events?: SessionEvent[]; next_events_cursor?: number | null; events_error?: string; }
export const readLogs = (sessionId: string, cursor = 0) => invoke<LogPage>('session_logs', { sessionId, cursor });
export const readEvents = (sessionId: string, cursor = 0) => invoke<LogPage>('session_events', { sessionId, cursor });

async function allEntries(sessionId: string, events: boolean) {
  const entries: SessionEvent[] = [];
  let cursor = 0, bytes = 0;
  const encoder = new TextEncoder();
  while (true) {
    const page = await (events ? readEvents : readLogs)(sessionId, cursor);
    for (const entry of page.entries) {
      bytes += encoder.encode(entry.message).length + 1;
      // Clipboard text must fit memory; never silently copy only part of an archive.
      if (bytes > 32 * 1024 * 1024) throw new Error('Archive exceeds the clipboard limit; no partial copy was made.');
      entries.push(entry);
    }
    if (page.next_cursor === null) return { entries, session: page.session, complete: events ? !!page.events_complete : page.logs_complete };
    if (page.next_cursor <= cursor) throw new Error('Session archive cursor did not advance. Refresh and retry.');
    cursor = page.next_cursor;
  }
}

export async function copySessionLogs(sessionId: string): Promise<boolean> {
  const data = await allEntries(sessionId, false);
  await copyText(data.entries.map(entry => entry.message).join('\n'));
  return data.complete;
}

export async function copySessionEvents(sessionId: string): Promise<void> {
  const data = await allEntries(sessionId, true);
  await copyText(sessionEvents(data.session, data.entries).map(entry => entry.message).join('\n'));
}
