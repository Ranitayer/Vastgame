"""Record CLI lifecycle output while preserving interactive terminal behavior."""
import codecs
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import termios
import uuid
from desktop_launch import phase
from session_history import ROOT, LogWriter, begin, finish_attempt, new_label
BIN = Path(__file__).resolve().parents[2]/'bin/vastgame'


def run(args):
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700); ROOT.chmod(0o700)
    capture = ROOT/('.capture-'+uuid.uuid4().hex)
    command = args[0] if args else 'start'
    label = new_label() if command == 'start' else None
    env = dict(os.environ, VASTGAME_HISTORY_CAPTURE='1', VASTGAME_HISTORY_CAPTURE_FILE=str(capture))
    if label:
        env['VASTGAME_LAUNCH_LABEL'] = label
        game = args[1] if len(args) > 1 and not args[1].startswith('-') else ''
        try: begin(label, game)
        except (OSError, ValueError): print('Warning: session history could not be created; rig operation continues.', file=sys.stderr)
    terminal = sys.stdout.isatty()
    master = slave = None
    if terminal:
        master, slave = pty.openpty()
        # Output-only PTY: stdin remains the real terminal, so prompts keep working.
        fcntl.ioctl(slave, termios.TIOCSWINSZ, fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, bytes(8)))
    process = subprocess.Popen([str(BIN), *args],
                               env=env, stdout=slave if terminal else subprocess.PIPE, stderr=subprocess.STDOUT)
    if slave is not None: os.close(slave)
    descriptor = master if terminal else process.stdout.fileno()
    def forward(signum, _frame):
        if process.poll() is None: process.send_signal(signum)
    previous = {sig: signal.signal(sig, forward) for sig in (signal.SIGINT, signal.SIGTERM)}
    def resize(_signum, _frame):
        if master is not None:
            try: fcntl.ioctl(master, termios.TIOCSWINSZ, fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, bytes(8)))
            except OSError: pass
    previous[signal.SIGWINCH] = signal.signal(signal.SIGWINCH, resize)
    decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
    buffer, pending, writer, logging_failed = '', [], LogWriter(label, phase) if label else None, False
    def record(line):
        nonlocal label, writer, logging_failed
        if logging_failed: return
        try:
            if not writer and capture.is_file():
                label = json.loads(capture.read_text())['label']; writer = LogWriter(label, phase)
                for earlier in pending: writer.append(earlier)
                pending.clear()
            if writer: writer.append(line)
            elif sum(map(len, pending)) < 1024*1024: pending.append(line)
        except (OSError, ValueError, KeyError):
            logging_failed = True
            print('\nWarning: session logging failed; the rig operation continues.', file=sys.stderr)
    try:
        while True:
            if not select.select([descriptor], [], [], 0.2)[0]:
                if process.poll() is not None: break
                continue
            try: block = os.read(descriptor, 8192)
            except OSError as exc:
                if terminal and exc.errno == errno.EIO: break
                raise
            if not block: break
            try: sys.stdout.buffer.write(block); sys.stdout.buffer.flush()
            except BrokenPipeError: pass  # Output closure must not cancel a rental.
            buffer += decoder.decode(block).replace('\r', '\n')
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1); record(line)
            while len(buffer) > 8192: record(buffer[:8192]); buffer = buffer[8192:]
        record(buffer+decoder.decode(b'', final=True))
        code = process.wait()
        if label:
            try: finish_attempt(label, code)
            except (OSError, ValueError): print('Warning: session completion could not be recorded.', file=sys.stderr)
        return code if code >= 0 else 128-code
    finally:
        for sig, handler in previous.items(): signal.signal(sig, handler)
        if master is not None: os.close(master)
        elif process.stdout: process.stdout.close()
        capture.unlink(missing_ok=True)


if __name__ == '__main__': sys.exit(run(sys.argv[1:]))
