"""Bounded, read-only VM samples; missing rendering metrics remain unknown."""
import csv
import io
import json
import math
from pathlib import Path
import subprocess
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
        stream.seek(max(0, p.stat().st_size - 16384))
        tail = stream.read(16384).decode(errors='replace').splitlines()
    columns = next((next(csv.reader([line])) for line in header if line.startswith('fps,frametime,')), None)
    if not columns:
        return {}
    for line in reversed(tail):
        values = next(csv.reader([line]))
        if len(values) != len(columns) or number(values[0]) is None:
            continue
        row = dict(zip(columns, values))
        return {key: number(row.get(source)) for key, source in
                [('game_fps', 'fps'), ('frametime_ms', 'frametime')]}
    return {}


class Collector:
    def __init__(self, gid, executable, root=Path('/vastgame-status')):
        self.gid, self.exe, self.root = gid, executable, root
        self.folder = Path.home() / '.local/state/vastgame/performance' / gid
        self.folder.mkdir(parents=True, exist_ok=True)
        self.started, self.previous = time.time(), {}
        self.stop = threading.Event()

    def sample(self):
        data = {'schema': 1, 'game_id': self.gid, 'updated': time.time(), 'source': 'VM + MangoHud'}
        data['session_id'] = json.loads((self.root / 'session.json').read_text()).get('session_id')
        data.update(mango_sample(self.folder, self.exe, self.started))
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
        try:
            result = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu',
                                     '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=2, check=True)
            # Vastgame currently rents one GPU; don't aggregate unrelated devices.
            row = next(csv.reader(result.stdout.splitlines()))
            data.update(zip(('gpu_pct', 'vram_used_mib', 'vram_total_mib', 'gpu_temp_c'), map(number, row)))
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
            self.stop.wait(2)

    def start(self):
        threading.Thread(target=self.run, name='vastgame-metrics', daemon=True).start()
        return self
