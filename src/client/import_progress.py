"""One terminal progress line, refreshed independently of blocking I/O."""
from collections import deque
from contextlib import contextmanager
import shutil
import sys
import threading
import time


class Progress:
    def __init__(self, stream=None):
        self.stream = stream or sys.stderr
        self.tty = self.stream.isatty()
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.started = time.monotonic()
        self.samples = deque()
        self.label = 'Preparing import'
        self.done = 0; self.total = None; self.detail = ''
        self.transfers = {}; self.verified = set(); self.produced = {}
        self.hidden = False
        self.thread = threading.Thread(target=self.refresh, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def phase(self, label, total=None, done=0, detail=''):
        with self.lock:
            self.label, self.total, self.done, self.detail = label, total, done, detail
            self.samples.clear()
            self.samples.append((time.monotonic(), done))

    def advance(self, amount):
        with self.lock: self.done += amount

    def part(self, name, size):
        with self.lock:
            self.produced[name] = size

    def upload(self, name, size):
        with self.lock:
            self.transfers[name] = max(self.transfers.get(name, 0), min(size, self.produced[name]))
            self.done = sum(self.transfers.values())
            self.detail = f'Chunks verified {len(self.verified)}/{len(self.produced)}'

    def verify(self, name):
        with self.lock:
            self.verified.add(name)
        self.upload(name, self.produced[name])

    def upload_total(self):
        with self.lock: self.total = sum(self.produced.values())

    def line(self, now):
        with self.lock:
            label, done, total, detail = self.label, self.done, self.total, self.detail
            self.samples.append((now, done))
            while len(self.samples) > 2 and now-self.samples[0][0] > 5:
                self.samples.popleft()
            first_time, first_done = self.samples[0]
            packed = sum(self.produced.values()) if label == '4/6 Packaging / uploading' else 0
        speed = max(0, done-first_done)/max(0.001, now-first_time)
        elapsed = int(now-self.started)
        spinner = '|/-\\'[int(now*10) % 4]
        if total is not None:
            percent = min(100, done*100/total) if total else 100
            filled = min(16, int(percent*16/100))
            status = f'[{"#"*filled}{"-"*(16-filled)}] {percent:5.1f}%  {done/1024**3:.2f}/{total/1024**3:.2f} GiB'
            remaining = max(0, total-done)/speed if speed else None
            eta = f'{int(remaining)//60}m {int(remaining)%60:02d}s' if remaining is not None else '--'
        else:
            status = f'[{spinner}] {done/1024**3:.2f} GiB' if done else f'[{spinner}]'
            eta = '-- (total pending)' if done else '--'
            if packed:
                percent = min(100, done*100/packed)
                status = f'[{spinner}] {done/1024**3:.2f}/{packed/1024**3:.2f} GiB packed ({percent:.1f}%)'
                remaining = max(0, packed-done)/speed if speed else None
                eta = f'queued {int(remaining)//60}m {int(remaining)%60:02d}s; total pending' if remaining is not None else '-- (total pending)'
        rate = f'{speed/1024**2:.1f} MiB/s' if speed else 'waiting'
        return f'{label} | {status} | {rate} | ETA {eta} | {elapsed//60}m {elapsed%60:02d}s' + (f' | {detail}' if detail else '')

    @contextmanager
    def pause(self):
        with self.lock:
            self.hidden = True
            if self.tty: self.stream.write('\n'); self.stream.flush()
        try: yield
        finally:
            with self.lock: self.hidden = False

    def render(self):
        with self.lock:
            if self.hidden: return
            line = self.line(time.monotonic())
            if self.tty:
                width = shutil.get_terminal_size((120, 24)).columns
                self.stream.write('\r\x1b[2K'+line[:max(1, width-1)])
            else:
                self.stream.write(line+'\n')
            self.stream.flush()

    def refresh(self):
        # Rendering never waits for network reads, extraction or remote verification.
        interval = 0.1 if self.tty else 5
        self.render()
        while not self.stop.wait(interval): self.render()

    def __exit__(self, exc_type, exc, tb):
        self.stop.set(); self.thread.join()
        if exc_type:
            label = 'Import cancelled' if issubclass(exc_type, KeyboardInterrupt) else 'Import failed'
            self.phase(label, detail='Staging retained; no unverified package selected')
        self.render()
        if self.tty: self.stream.write('\n'); self.stream.flush()
