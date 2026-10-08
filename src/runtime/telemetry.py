"""Bounded, read-only VM samples; missing rendering metrics remain unknown."""
import csv
import io
import json
import math
from pathlib import Path
import subprocess
import socket
import uuid
import threading
import time


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) and result >= 0 else None
    except (TypeError, ValueError):
        return None


def mango_sample(folder, executable, started, now=None):
    now = time.time() if now is None else now
    name = Path(executable).name.lower()
    names = (name + '_', Path(name).stem + '_')
    files = []
    for p in folder.glob('*.csv'):
        if p.name.lower().startswith(names) and not p.name.endswith('_summary.csv'):
            stat = p.stat()
            if stat.st_mtime >= started and 0 <= now - stat.st_mtime < 5:
                files.append((stat.st_mtime, p))
    if not files:
        return {}
    p = max(files)[1]
    with p.open('rb') as stream:
        header = stream.read(8192).decode(errors='replace').splitlines()
    columns = None
    for line in header:
        values = [value.strip() for value in next(csv.reader([line]))]
        if {'fps', 'frametime'} <= set(values):
            columns = values
            break
    if not columns:
        return {}
    # A writer may be midway through its last row; never accept truncated data.
    with p.open('rb') as stream:
        stream.seek(max(0, p.stat().st_size - 16384))
        raw = stream.read(16384)
    tail = raw.decode(errors='replace').splitlines()
    if raw and not raw.endswith(b'\n'): tail = tail[:-1]
    for line in reversed(tail):
        values = next(csv.reader([line]))
        if len(values) != len(columns): continue
        row = dict(zip(columns, values))
        fps, frametime = number(row.get('fps')), number(row.get('frametime'))
        if fps is None or frametime is None or frametime <= 0: continue
        data = dict(game_fps=fps, frametime_ms=frametime)
        for key, column in [('cpu_temp_c', 'cpu_temp'), ('gpu_clock_mhz', 'gpu_core_clock'),
                            ('gpu_memory_clock_mhz', 'gpu_mem_clock'), ('gpu_power_w', 'gpu_power')]:
            value = number(row.get(column))
            if value is not None and value > 0: data[key] = value
        return data
    return {}


def mango_environment(folder, control):
    return dict(MANGOHUD='1', MANGOHUD_CONFIG='no_display=1,autostart_log=1,log_interval=500,'
                'log_duration=0,permit_upload=0,gpu_power=1,cpu_temp=1,gpu_core_clock=1,gpu_mem_clock=1,'
                'control='+control+'%p,output_folder='+str(folder))


def start_mango_logging(prefix, connected, unix=Path('/proc/net/unix')):
    names = {line.split()[-1] for line in unix.read_text().splitlines()
             if line.split() and line.split()[-1].startswith('@'+prefix)}
    connected.intersection_update(names)
    for name in names-connected:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(0.1)
                client.connect('\0'+name[1:])
                client.sendall(b':logging=1;')
            connected.add(name)
        except OSError:
            pass  # A renderer may have exited between discovery and connection.



class Collector:
    def __init__(self, gid, executable, root=Path('/vastgame-status')):
        self.gid, self.exe, self.root = gid, executable, root
        token = uuid.uuid4().hex
        self.control = 'vastgame-'+token+'-'
        self.folder = Path.home() / '.local/state/vastgame/performance' / gid / token
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.started, self.previous = time.time(), {}
        self.stop = threading.Event()
        self.connected = set()
        self.hardware = {}; self.hardware_at = 0; self.hardware_attempt = float('-inf')

    def sample(self):
        data = {'schema': 1, 'game_id': self.gid, 'updated': time.time(), 'source': 'VM + MangoHud'}
        data['session_id'] = json.loads((self.root / 'session.json').read_text()).get('session_id')
        try: start_mango_logging(self.control, self.connected)
        except OSError: pass
        game = mango_sample(self.folder, self.exe, self.started)
        data.update(game)
        data['game_metrics_source'] = 'MangoHud'
        data['game_metrics_status'] = 'live' if game else 'waiting'
        data['game_metrics_note'] = '' if game else ('Waiting for MangoHud game frames' if time.time()-self.started < 60
                                                   else 'No game samples; check MangoHud injection in the launch log')
        loads = []
        for line in Path('/proc/stat').read_text().splitlines():
            if not line.startswith('cpu'):
                continue
            fields = line.split(); values = list(map(int, fields[1:9]))
            total, idle = sum(values), values[3] + values[4]
            old = self.previous.get(fields[0]); self.previous[fields[0]] = (total, idle)
            if old and total > old[0]:
                load = 100 * (1 - (idle - old[1]) / (total - old[0]))
                if fields[0] == 'cpu': data['cpu_pct'] = round(load, 1)
                else: loads.append(load)
        if loads: data['cpu_max_core_pct'] = round(max(loads), 1)
        memory = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
        data['ram_total_gib'] = memory['MemTotal'] / 1048576
        data['ram_used_gib'] = (memory['MemTotal'] - memory['MemAvailable']) / 1048576
        if time.monotonic()-self.hardware_attempt < 2:
            if time.time()-self.hardware_at < 6: data.update(self.hardware)
            return data
        self.hardware_attempt = time.monotonic()
        try:
            result = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu',
                                     '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=2, check=True)
            # Vastgame currently rents one GPU; don't aggregate unrelated devices.
            row = next(csv.reader(result.stdout.splitlines()))
            self.hardware = dict(zip(('gpu_pct', 'vram_used_mib', 'vram_total_mib', 'gpu_temp_c'), map(number, row)))
            self.hardware_at = time.time(); data.update(self.hardware)
        except (OSError, subprocess.SubprocessError, StopIteration):
            data['hardware_note'] = 'NVIDIA metrics unavailable'
        return data

    def run(self):
        while not self.stop.is_set():
            try:
                sample = self.sample()
                tmp = self.root / 'performance.tmp'
                tmp.write_text(json.dumps(sample, allow_nan=False)); tmp.replace(self.root / 'performance.json')
            except Exception as exc:
                print('Performance telemetry unavailable: ' + str(exc), flush=True)
            self.stop.wait(0.5)

    def start(self):
        threading.Thread(target=self.run, name='vastgame-metrics', daemon=True).start()
        return self
