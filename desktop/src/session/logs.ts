export interface LogEntry { time: number; level: 'info' | 'success' | 'warning' | 'error'; scope: string; message: string; }

export function importantLog(raw: string, time = Date.now()): LogEntry | null {
  if (!Number.isFinite(time) || Number.isNaN(new Date(time).valueOf())) time = Date.now();
  let message = raw.trim();
  if (!message || /^VASTGAME\s*\||^[━─═]+$|^\[VASTGAME_(GAME_REQUESTED|PROGRESS|CREATE_REQUESTED|DESKTOP)\]/.test(message)) return null;
  if (message.startsWith('[VASTGAME_ERROR]')) {
    try {
      const error = JSON.parse(message.slice('[VASTGAME_ERROR]'.length));
      if (typeof error?.code === 'string' && typeof error.message === 'string') message = `[${error.code}] ${error.message}`;
    } catch { /* Keep malformed error evidence visible. */ }
  }
  let level: LogEntry['level'] = /^(ERROR:|E:)|^\[(?!PRICE_CONFIRMATION\])(?=[A-Z_]*_)[A-Z_]+\]|\b(error|failed|failure|insufficient)\b/i.test(message) ? 'error'
    : /^⚠|\[PRICE_CONFIRMATION\]|\b(retained|unavailable|ignored|waiting.*lock)\b/i.test(message) ? 'warning'
    : /^✓|^(Verified|Reused)\b|Game running|Game process detected/i.test(message) ? 'success' : 'info';
  const stage = message.match(/^Stage (\d)\/3/);
  if (stage) message = ({ '1': 'Creating rig', '2': 'Connecting rig network', '3': 'Restoring game and runtime' } as Record<string, string>)[stage[1]] || message;
  else if (/^Stage: /.test(message)) message = message.slice(7);
  else if (!/^(✓|⚠|ERROR:|E:|\[[A-Z_]+\]|Cause:|Evidence:|Trigger:|Report:|Quote verified:|Game quote:|Game:|Streaming |Video codec:|Checking Moonlight|Backing up|Closing the game|Game ignored|Destroying Vast|Verified |Reused )/.test(message) && level === 'info') return null;
  message = message.replace(/^[✓⚠]\s*/, '').replace(/^ERROR:\s*/, '');
  const quote = message.match(/^(?:Quote verified:|Game quote:)\s*\$?([\d.]+)(?:\s*USD)?\/h\s*with\s*(\d+)\s*GB allocated/);
  if (quote) message = `Quote $${Number(quote[1]).toFixed(4)}/h · ${quote[2]} GB disk`;
  if (/^Game: Configured game process detected|^Game process detected\./.test(message)) { message = 'Game process running'; level = 'success'; }
  if (/^Tailscale online:/.test(message)) message = 'Rig network connected';
  const scope = /shut|destroy|clos(?:ing|ed).*game|game closed|terminating|game ignored/i.test(message) ? 'STOP'
    : /saves|configs|shaders|backup|state backup/i.test(message) ? 'SAVES'
    : /Moonlight|stream|codec|pairing/i.test(message) ? 'STREAM'
    : /game|runtime|restore|Lutris|Proton/i.test(message) ? 'GAME' : 'RIG';
  return { time, level, scope, message };
}

export function appendLogs(entries: LogEntry[], pending: LogEntry[]): LogEntry[] {
  const result = [...entries];
  for (const entry of pending) {
    const last = result[result.length - 1];
    if (last?.message !== entry.message || last.level !== entry.level) result.push(entry);
  }
  return result.slice(-500);
}
