"""Read session-bound VM telemetry without blocking the local HUD or menu."""
import json
import math
import re
import shlex
import subprocess
import threading
import time
import urllib.request


def merge_vm_metrics(metrics, vm, meta, now=None, max_age=6):
    if not isinstance(vm, dict): return False
    updated = vm.get('updated')
    now = time.time() if now is None else now
    if (not meta.get('session_id') or vm.get('game_id') != meta.get('game_id')
            or vm.get('session_id') != meta['session_id'] or type(updated) not in (int, float)
            or not math.isfinite(updated) or not 0 <= now-updated < max_age):
        return False
    metrics.update({key: value for key, value in vm.items() if key not in ('schema', 'updated', 'source')
                    and type(value) in (int, float) and math.isfinite(value) and value >= 0})
    for key in ('game_metrics_source', 'game_metrics_status', 'game_metrics_note'):
        if isinstance(vm.get(key), str): metrics[key] = ' '.join(vm[key].split())[:120]
    return True


SSH_READER = '''
from pathlib import Path
import sys,time
root=Path('/var/lib/vast-gaming/status')
while True:
    if (root/'instance-label').read_text().strip() != sys.argv[1]:
        raise SystemExit('VM launch identity changed')
    try:
        path=root/'performance.json'
        text=path.read_text() if path.stat().st_size <= 16384 else '{}'
    except OSError:
        text='{}'
    print(text,flush=True)
    time.sleep(1)
'''


class VMFeed:
    def __init__(self, ip, meta, known_hosts):
        self.ip, self.meta, self.known_hosts = ip, meta, str(known_hosts)
        self.packet = {}; self.error = ''
        self.lock = threading.Lock(); self.stop = threading.Event()
        self.process = None; self.thread = None

    def accept(self, packet, now=None):
        if not merge_vm_metrics({}, packet, self.meta, now): return False
        with self.lock:
            if packet['updated'] >= self.packet.get('updated', 0):
                self.packet = dict(packet); self.error = ''
        return True

    def views(self, now=None):
        now = time.time() if now is None else now
        with self.lock: packet, error = dict(self.packet), self.error
        live = {}
        if merge_vm_metrics(live, packet, self.meta, now): return live, dict(live)
        display = {}
        if merge_vm_metrics(display, packet, self.meta, now, max_age=30):
            display['game_metrics_status'] = 'delayed'
            display['game_metrics_note'] = f"VM telemetry delayed · last sample {now-packet['updated']:.0f}s ago"
        else:
            display['game_metrics_note'] = 'VM telemetry unavailable' if error else 'Waiting for VM telemetry'
        return live, display

    def ssh(self):
        label = self.meta.get('label', '')
        if not isinstance(label, str) or not re.fullmatch(r'vastgame-[0-9]+', label): return
        seen = set()
        for endpoint in self.meta.get('ssh_endpoints', []):
            host, port = endpoint.get('host'), endpoint.get('port')
            try: port = int(port)
            except (TypeError, ValueError): continue
            if (not isinstance(host, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.:-]*', host)
                    or not 1 <= port <= 65535 or (host, port) in seen): continue
            seen.add((host, port))
            if self.stop.is_set(): return
            command = ['ssh', '-F', '/dev/null', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=6',
                       '-o', 'ConnectionAttempts=1', '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=1',
                       '-o', 'StrictHostKeyChecking=accept-new', '-o', 'UserKnownHostsFile='+self.known_hosts,
                       '-p', str(port), 'root@'+host,
                       'python3 -u -c '+shlex.quote(SSH_READER)+' '+shlex.quote(label)]
            process = None
            try:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                           text=True)
                with self.lock: self.process = process
                last_valid = time.monotonic()
                connected = False
                while not self.stop.is_set():
                    line = process.stdout.readline(16385)
                    if not line or len(line) > 16384: break
                    try:
                        if self.accept(json.loads(line)):
                            last_valid = time.monotonic()
                            if not connected:
                                print('VM telemetry: verified SSH fallback connected', flush=True)
                                connected = True
                    except ValueError: pass
                    if time.monotonic()-last_valid > 15: break
            except OSError:
                pass
            finally:
                if process is not None:
                    if process.poll() is None:
                        try: process.terminate()
                        except ProcessLookupError: pass
                    try: process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        try: process.kill()
                        except ProcessLookupError: pass
                        process.wait()
                    process.stdout.close()
                with self.lock: self.process = None

    def run(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        last_ssh = float('-inf')
        while not self.stop.is_set():
            try:
                with opener.open(f'http://{self.ip}:48199/performance.json', timeout=4) as response:
                    raw = response.read(16385)
                if len(raw) > 16384: raise ValueError('VM telemetry packet is too large')
                packet = json.loads(raw)
                if not self.accept(packet): raise ValueError('VM telemetry is stale or belongs to another session')
            except (OSError, ValueError) as exc:
                with self.lock:
                    changed = self.error != str(exc)
                    self.error = str(exc)
                if changed: print('VM telemetry HTTP: '+str(exc), flush=True)
                if time.monotonic()-last_ssh >= 30:
                    last_ssh = time.monotonic()
                    self.ssh()
            self.stop.wait(1)

    def start(self):
        self.thread = threading.Thread(target=self.run, name='vastgame-vm-telemetry', daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.stop.set()
        with self.lock: process = self.process
        if process is not None and process.poll() is None:
            try: process.terminate()
            except ProcessLookupError: pass
        if self.thread is not None: self.thread.join(timeout=1)
