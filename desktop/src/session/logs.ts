export interface LogEntry { level: 'info' | 'success' | 'warning' | 'error'; message: string; }

export function formatLog(raw: string): LogEntry | null {
  const message = raw.trim();
  if (!message) return null;
  const level: LogEntry['level'] = /^(ERROR:|E:)|^\[(?!PRICE_CONFIRMATION\])(?=[A-Z_]*_)[A-Z_]+\]|\b(error|failed|failure|insufficient)\b/i.test(message) ? 'error'
    : /^⚠|\[PRICE_CONFIRMATION\]|\b(retained|unavailable|ignored|waiting.*lock)\b/i.test(message) ? 'warning'
    : /^✓|^(Verified|Reused)\b|Game running|Game process detected/i.test(message) ? 'success' : 'info';
  return { level, message: raw };
}

export function appendLogs(entries: LogEntry[], pending: LogEntry[]): LogEntry[] {
  return [...entries, ...pending].slice(-500);
}
