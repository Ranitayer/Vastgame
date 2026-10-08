"""Merge measured client/VM telemetry. No inferred FPS or invented latency."""
import argparse
from collections import deque
import fcntl
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import time
from vm_telemetry import VMFeed, merge_vm_metrics


def atomic(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(value); tmp.replace(path)


def read_json(path):
    try: return json.loads(path.read_text())
    except (OSError, ValueError): return {}


def parse_moonlight(text):
    patterns = {
        'stream_fps': r'Rendering frame rate: ([\d.]+) FPS',
        'incoming_fps': r'Incoming frame rate from network: ([\d.]+) FPS',
        'decode_fps': r'Decoding frame rate: ([\d.]+) FPS',
        'network_drop_pct': r'Frames dropped by your network connection: ([\d.]+)%',
        'pacing_drop_pct': r'Frames dropped due to network jitter: ([\d.]+)%',
        'rtt_ms': r'Average network latency: ([\d.]+) ms',
        'rtt_variance_ms': r'variance: ([\d.]+) ms',
        'decode_ms': r'Average decoding time: ([\d.]+) ms',
        'queue_ms': r'Average frame queue delay: ([\d.]+) ms',
        'render_ms': r'Average rendering time.*?: ([\d.]+) ms',
        'bitrate_mbps': r'Bitrate: ([\d.]+) Mbps',
        # This includes host capture/processing/encode; never label pure encode.
        'host_processing_ms': r'Host processing latency min/max/average: [\d.]+/[\d.]+/([\d.]+) ms',
    }
    data = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            value = float(match[1])
            if math.isfinite(value): data[key] = value
    match = re.search(r'Video stream: (\d+x\d+) [\d.]+ FPS \(Codec: ([^)]+)\)', text)
    if match: data.update(resolution=match[1], codec=match[2])
    return data


def penalty(value, ideal, poor):
    return max(0, min(100, 100 * (poor - value) / (poor - ideal)))


def assess(m, fps):
    budget = 1000 / fps
    components = {}
    if 'game_fps' in m and 'frametime_ms' in m:
        components['Game performance'] = min(100, 100 * m['game_fps'] / fps,
                                            penalty(m['frametime_ms'], budget * 1.1, budget * 3))
    if 'rtt_ms' in m:
        network = penalty(m['rtt_ms'], 20, 150)
        for key, ideal, poor in [('jitter_ms', 2, 20), ('probe_loss_pct', 0, 3),
                                 ('network_drop_pct', 0, 3), ('pacing_drop_pct', 0, 5)]:
            if key in m: network = min(network, penalty(m[key], ideal, poor))
        if m.get('route') == 'relayed': network = min(network, 85)
        components['Network'] = network
    if 'decode_ms' in m: components['Client decode'] = penalty(m['decode_ms'], budget * .25, budget * 1.5)
    if 'stream_fps' in m: components['Stream delivery'] = min(100, 100 * m['stream_fps'] / fps)
    if 'host_processing_ms' in m: components['Host pipeline'] = penalty(m['host_processing_ms'], budget * .5, budget * 2)
    if 'gpu_temp_c' in m: components['Thermals'] = penalty(m['gpu_temp_c'], 80, 100)
    for kind, used, total in [('RAM pressure','ram_used_gib','ram_total_gib'), ('VRAM pressure','vram_used_mib','vram_total_mib')]:
        if m.get(total, 0) > 0 and used in m:
            components[kind] = penalty(100 * m[used] / m[total], 95, 100)
    required = ('game_fps', 'frametime_ms', 'stream_fps', 'decode_ms', 'rtt_ms', 'jitter_ms',
                'network_drop_pct', 'probe_loss_pct', 'host_processing_ms', 'gpu_pct', 'gpu_temp_c',
                'cpu_pct', 'ram_used_gib', 'vram_used_mib', 'codec', 'bitrate_mbps', 'resolution', 'route')
    coverage = sum(k in m and (k != 'route' or m[k] in ('direct','relayed')) for k in required) / len(required)
    if not components: return {'score': None, 'coverage': 0, 'bottleneck': 'Waiting for measurements', 'components': {}}
    weakest = min(components, key=components.get)
    score = round(min(components.values()))
    if coverage < 1: score = min(score, 99)
    label = weakest + '-bound' if score < 95 else 'Meeting measured targets'
    if weakest == 'Game performance' and score < 95:
        if m.get('gpu_pct', 0) >= 95: label = 'Likely GPU-bound'
        elif m.get('cpu_max_core_pct', 0) >= 95: label = 'Likely CPU-bound'
        else: label = 'Game / frame pacing limited'
    if weakest == 'Client decode' and score < 95: label = 'Likely client-decode-bound'
    if weakest == 'Network' and score < 95: label = 'Likely network-bound'
    return {'score': score, 'coverage': round(coverage * 100), 'bottleneck': label, 'components': components}


def fmt(m, key, unit='', precision=1):
    value = m.get(key)
    return f'{value:.{precision}f}{unit}' if isinstance(value, (float, int)) else '—'


def hud_lines(m, quality, fps):
    # One dense layout. Colors describe categories and flag measured degradation.
    def colored(text, base, component=None):
        value = quality['components'].get(component)
        color = 'ff7979' if value is not None and value < 60 else 'ffd166' if value is not None and value < 85 else base
        return '#' + color + '|' + text

    score = quality['score']
    title = f'VASTGAME · FEEL {score}%' if score is not None else 'VASTGAME · FEEL —'
    if quality['coverage'] < 100: title += f" · data {quality['coverage']}%"
    status = 'ff7979' if score is not None and score < 60 else 'ffd166' if score is not None and score < 85 else '65e6ac' if score is not None else '8c9bac'
    vram_used = m.get('vram_used_mib')
    vram_total = m.get('vram_total_mib')
    vram = f'{vram_used/1024:.1f}/{vram_total/1024:.1f} GiB' if vram_used is not None and vram_total else '—'
    return [
        colored(title, status),
        colored(f"Game {fmt(m,'game_fps',' FPS')} · {fmt(m,'frametime_ms',' ms')} · stream {fmt(m,'stream_fps',' FPS')}", '65e6ac', 'Game performance'),
        colored(f"{m.get('resolution','—')} @ {fps} Hz target · {m.get('codec','—')} · {fmt(m,'bitrate_mbps',' Mbps')}", '8bc7ff', 'Stream delivery'),
        colored(f"GPU {fmt(m,'gpu_pct','%')} · {fmt(m,'gpu_temp_c','°C')} · VRAM {vram} · {fmt(m,'gpu_power_w',' W')} · {fmt(m,'gpu_clock_mhz',' MHz',0)}", 'c5a3ff', 'Thermals'),
        colored(f"CPU {fmt(m,'cpu_pct','%')} / core {fmt(m,'cpu_max_core_pct','%')} · {fmt(m,'cpu_temp_c','°C')} · RAM {fmt(m,'ram_used_gib')} / {fmt(m,'ram_total_gib',' GiB')}", 'e4b5ee', 'RAM pressure'),
        colored(f"Decode {fmt(m,'decode_ms',' ms')} · host {fmt(m,'host_processing_ms',' ms')} · queue {fmt(m,'queue_ms',' ms')}", '89dceb', 'Client decode'),
        colored(f"RTT {fmt(m,'rtt_ms',' ms')} · probe jitter {fmt(m,'jitter_ms',' ms')} · {m.get('route','unknown')}", '89dceb', 'Network'),
        colored(f"Video drops {fmt(m,'network_drop_pct','%')} · pacing {fmt(m,'pacing_drop_pct','%')} · probe loss {fmt(m,'probe_loss_pct','%')}", '8bc7ff', 'Network'),
        colored(f"Rx {fmt(m,'incoming_fps',' FPS')} · decoded {fmt(m,'decode_fps',' FPS')} · render {fmt(m,'render_ms',' ms')}", 'b9cadb', 'Stream delivery'),
        colored(f"RTT variance {fmt(m,'rtt_variance_ms',' ms')} · {quality['bottleneck']}", status),
        colored(m.get('game_metrics_note') or 'Game source: MangoHud · Ctrl+Alt+Shift+H', '8c9bac'),
    ]


def route(ip):
    try:
        result = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=2, check=True)
        peers = json.loads(result.stdout).get('Peer', {}).values()
        peer = next(p for p in peers if ip in p.get('TailscaleIPs', []))
        if not peer.get('Online', False): return 'offline'
        if peer.get('CurAddr'): return 'direct'
        if peer.get('Relay'): return 'relayed'
    except (OSError, ValueError, subprocess.SubprocessError, StopIteration): pass
    return 'unknown'


def process_identity(pid):
    try:
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return fields[19] if fields[0] != 'Z' else None
    except OSError: return None


def save_history(path, meta, samples):
    # Require a real gameplay window; never rank hosts on missing game samples.
    valid = [s for s in samples if 'game_fps' in s['metrics'] and 'stream_fps' in s['metrics'] and 'rtt_ms' in s['metrics']]
    if len(valid) < 30 or not meta.get('machine_id'): return
    scores = [s['quality']['score'] for s in valid if s['quality']['score'] is not None]
    if not scores: return
    # Host ranking excludes client decode and GPU/game workload: compare measured
    # network + host pipeline instead, and retain game/target context for review.
    delivery = [min(s['quality']['components'][k] for k in ('Network', 'Host pipeline')
                    if k in s['quality']['components']) for s in valid]
    summary = dict(meta, updated=time.time(), samples=len(valid), feel=round(statistics.median(scores)),
                   delivery_score=round(statistics.median(delivery)),
                   rtt_ms=round(statistics.median(s['metrics']['rtt_ms'] for s in valid), 2),
                   game_fps=round(statistics.median(s['metrics']['game_fps'] for s in valid), 2))
    keys = {k for sample in valid for k,v in sample['metrics'].items() if isinstance(v, (int,float))}
    summary['median_metrics'] = {key: round(statistics.median(s['metrics'][key] for s in valid if key in s['metrics']), 3)
                                 for key in keys}
    frames = sorted(s['metrics']['frametime_ms'] for s in valid if 'frametime_ms' in s['metrics'])
    if frames: summary['p95_frametime_ms'] = frames[min(len(frames)-1, math.ceil(len(frames)*.95)-1)]
    summary['game_delivery_score'] = round(statistics.median(s['quality']['components'].get('Game performance',0) for s in valid))
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        history = read_json(path)
        key = 'machine:' + str(meta['machine_id'])
        entry = history.setdefault(key, {})
        previous = [s for s in entry.get('performance_sessions', []) if s.get('session_key') != meta.get('session_key')]
        entry['performance_sessions'] = (previous + [summary])[-10:]
        entry['performance'] = summary
        atomic(path, json.dumps(history, indent=2))


def append_metrics(path, sample):
    # Bound a long-running session to two 16 MiB files; history keeps its summary.
    if path.exists() and path.stat().st_size >= 16*1024**2:
        path.replace(path.with_name(path.name+'.1'))
    with path.open('a') as output:
        output.write(json.dumps(sample, allow_nan=False)+'\n')


def apply_menu_request(directory, settings_path):
    request = directory / 'menu.request'
    processing = directory / 'menu.processing'
    try: request.replace(processing)
    except FileNotFoundError: return
    staging = settings_path.with_name(settings_path.name + '.menu.tmp')
    try:
        if processing.stat().st_size > 1024: raise ValueError('Menu request is too large')
        resolution, fps, bitrate, codec, vsync, pacing = processing.read_text().strip().split('|')
        if vsync not in ('true', 'false') or pacing not in ('true', 'false'):
            raise ValueError('Invalid switch value')
        from stream_settings import read
        settings = read(settings_path)
        settings.update(resolution=resolution, fps=fps if fps == 'native' else int(fps),
                        bitrate_mbps=None if bitrate == 'auto' else int(bitrate), video_codec=codec)
        settings['moonlight_options'].update(vsync=vsync == 'true', **{'frame-pacing': pacing == 'true'})
        staging.write_text(json.dumps(settings, indent=2) + '\n')
        read(staging)  # Apply the same validation used by streamedit and launch.
        staging.replace(settings_path)
        atomic(directory / 'menu.status', 'Saved · reconnect to apply')
    except (OSError, ValueError, TypeError) as exc:
        atomic(directory / 'menu.status', 'Could not save stream settings')
        print('Stream menu save failed: ' + str(exc), flush=True)
    finally:
        processing.unlink(missing_ok=True)
        staging.unlink(missing_ok=True)


def run(args):
    directory = Path(args.directory)
    meta = read_json(directory / 'host.json')
    identity = process_identity(args.pid)
    if not identity: return
    probes, samples = deque(maxlen=60), deque(maxlen=1800)
    started, last_route, last_history = time.monotonic(), 0, time.monotonic()
    route_name = 'unknown'
    feed = VMFeed(args.ip, meta, args.known_hosts).start()
    # Fresh file per stream prevents old telemetry being shown on reconnect.
    log = directory / 'metrics.jsonl'
    try:
        while process_identity(args.pid) == identity:
            tick = time.monotonic()
            apply_menu_request(directory, Path(args.settings))
            m = {}
            raw = directory / 'moonlight.txt'
            try:
                if 0 <= time.time() - raw.stat().st_mtime < 5:
                    m.update(parse_moonlight(raw.read_text()[:8192]))
            except OSError: pass
            vm, vm_display = feed.views()
            m.update(vm)
            if not vm: m['game_metrics_note'] = vm_display['game_metrics_note']
            try:
                result = subprocess.run(['ping', '-n', '-c', '1', '-W', '1', args.ip],
                                        capture_output=True, text=True, timeout=2)
                match = re.search(r'time[=<]([\d.]+)', result.stdout)
                probes.append(float(match[1]) if match else None)
            except (OSError, subprocess.SubprocessError): probes.append(None)
            rtts = [v for v in probes if v is not None]
            if len(probes) >= 5:
                m['probe_loss_pct'] = 100 * (len(probes) - len(rtts)) / len(probes)
                differences = [abs(a-b) for a,b in zip(probes, list(probes)[1:]) if a is not None and b is not None]
                if differences: m['jitter_ms'] = statistics.mean(differences)
            if 'rtt_ms' not in m and rtts: m['rtt_ms'] = statistics.mean(rtts)
            if tick - last_route > 5:
                route_name, last_route = route(args.ip), tick
            m['route'] = route_name
            quality = assess(m, args.fps)
            sample = {'updated': time.time(), 'metrics': m, 'quality': quality}
            samples.append(sample); append_metrics(log, sample)
            atomic(directory / 'latest.json', json.dumps(sample, allow_nan=False))
            # Older VM samples are labeled in the display, never scored or stored as live metrics.
            atomic(directory / 'hud.txt', '\n'.join(hud_lines({**vm_display, **m}, quality, args.fps)))
            if tick - last_history >= 60:
                save_history(Path(args.history), meta, list(samples)); last_history = tick
            time.sleep(max(.1, 1 - (time.monotonic() - tick)))
    finally:
        feed.close()
        if time.monotonic() - started >= 60:
            save_history(Path(args.history), meta, list(samples))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--directory', required=True)
    parser.add_argument('--ip', required=True)
    parser.add_argument('--pid', type=int, required=True)
    parser.add_argument('--fps', type=int, required=True)
    parser.add_argument('--history', required=True)
    parser.add_argument('--settings', required=True)
    parser.add_argument('--known-hosts', required=True)
    arguments = parser.parse_args()
    if not 10 <= arguments.fps <= 1000: parser.error('Invalid stream FPS')
    run(arguments)
