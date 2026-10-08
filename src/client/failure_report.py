"""Private, redacted evidence for an exact Vast instance; never changes the VM."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

LIMIT = 16 * 1024 * 1024
FIELDS = ('id', 'machine_id', 'host_id', 'label', 'image', 'image_uuid', 'actual_status',
          'intended_status', 'next_state', 'status_msg', 'status_message', 'error_msg',
          'error', 'message', 'ssh_host', 'ssh_port', 'public_ipaddr', 'ports', 'gpu_name')


def redact(text):
    text = re.sub(r'https?://[^\s\"\'<>]+', '[URL redacted]', text)
    text = re.sub(r'(?i)([\"\']?(?:[\w-]*(?:token|password|secret|api_key|authkey|authorization|'
                  r'private_key|config_b64)[\w-]*)[\"\']?\s*[:=]\s*)'
                  r'(\"[^\"]*\"|\'[^\']*\'|[^\s,}]+)', r'\1[redacted]', text)
    text = re.sub(r'(?i)\bBearer\s+\S+|\btskey-[\w-]+', '[redacted]', text)
    text = re.sub(r'-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----',
                  '[private key redacted]', text, flags=re.S)
    return text


def write(path, text, sanitize=True):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(redact(text) if sanitize else text)
    temporary.chmod(0o600)
    temporary.replace(path)


def clean(value):
    if isinstance(value, str): return redact(value)
    if isinstance(value, list): return [clean(v) for v in value]
    if isinstance(value, dict):
        return {k: '[redacted]' if re.search(r'token|secret|password|api_key|authkey', k, re.I)
                else clean(v) for k, v in value.items()}
    return value


def json_write(path, value):
    # Redact strings before serialization so JSON stays valid.
    write(path, json.dumps(clean(value), indent=2)+'\n', sanitize=False)


def read(path, default=None):
    try: return json.loads(path.read_text())
    except (OSError, ValueError): return default if default is not None else {}


def event(folder, info, game):
    info = clean({key: info[key] for key in FIELDS if key in info})
    previous = read(folder/'instance.json')
    if previous != info:
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        folder.chmod(0o700)
        with (folder/'timeline.jsonl').open('a') as output:
            output.write(json.dumps(dict(time=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                                         instance=info))+'\n')
        (folder/'timeline.jsonl').chmod(0o600)
    json_write(folder/'instance.json', info)
    if game: json_write(folder/'game.json', dict(game=game))
    if info.get('actual_status') == 'running':
        state = folder.parent.parent
        history_path = state/'host_history.json'
        if not history_path.exists(): return
        with (state/'host_history.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            history = json.loads(history_path.read_text())
            item = history.get(f'machine:{info.get("machine_id")}', {})
            old = item.get('provisioning_failures', [])
            remaining = [failure for failure in old if failure['instance'] != str(info['id'])]
            if remaining != old:
                item['provisioning_failures'] = remaining
                item['last_boot_recovery'] = dict(instance=str(info['id']), time=time.time())
                json_write(history_path, history)


def capture(folder, name, args, timeout=20):
    # Bound process time and disk usage; diagnostics must not hang a failed launch.
    try:
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        import selectors
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        blocks = []; size = 0; deadline = time.monotonic()+timeout
        try:
            while size < LIMIT and time.monotonic() < deadline:
                if not selector.select(min(0.5, max(0, deadline-time.monotonic()))): continue
                block = os.read(process.stdout.fileno(), min(65536, LIMIT-size))
                if not block: break
                blocks.append(block); size += len(block)
        finally:
            selector.close(); process.stdout.close()
            if process.poll() is None:
                try: process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    blocks.append(b'\n[collection stopped: time or size limit]\n')
            process.wait()
        text = b''.join(blocks).decode(errors='replace')
        if process.returncode: text += f'\n[collector exit {process.returncode}]\n'
    except OSError as exc: text = f'[collection unavailable: {exc}]\n'
    write(folder/name, text)
    return text


def guest(folder, info, ip=''):
    label = info.get('label', '')
    if not re.fullmatch(r'vastgame-[0-9]+', label): return
    if re.fullmatch(r'100\.[0-9]+\.[0-9]+\.[0-9]+', ip):
        try:
            with urllib.request.urlopen(f'http://{ip}:48199/instance-label', timeout=3) as response:
                if response.read(128).decode().strip() != label: raise ValueError('Peer identity mismatch')
            for name in ('bootstrap.log', 'game.log', 'launch.json', 'progress.json'):
                try:
                    with urllib.request.urlopen(f'http://{ip}:48199/{name}', timeout=3) as response:
                        write(folder/('http-'+name), response.read(LIMIT).decode(errors='replace'))
                except (OSError, ValueError) as exc: write(folder/('http-'+name), str(exc))
        except (OSError, ValueError) as exc: write(folder/'http-unavailable.txt', str(exc))
    endpoints = [(info.get('ssh_host'), info.get('ssh_port'))]
    endpoints += [(info.get('public_ipaddr'), p.get('HostPort'))
                  for p in info.get('ports', {}).get('22/tcp', [])]
    seen = set()
    for host, port in endpoints[:3]:
        if not isinstance(host, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.:-]*', host): continue
        if not str(port).isdigit() or not 1 <= int(port) <= 65535: continue
        if (host, str(port)) in seen: continue
        seen.add((host, str(port)))
        command = '''test "$(cat /var/lib/vast-gaming/status/instance-label 2>/dev/null)" = LABEL || exit 42
echo '=== BOOTSTRAP (full, collection size capped) ==='
cat /var/log/vast-gaming-bootstrap.log 2>/dev/null
echo '=== STATUS ==='
cat /var/lib/vast-gaming/status/{error,phase,session,launch,progress}.json 2>/dev/null
echo '=== PREPARATION / GAME / PROTON (latest 5000 lines per log) ==='
find /srv/gaming/profiles -maxdepth 3 -type f -name '*.log' -exec tail -n 5000 {} + 2>/dev/null
echo '=== NVIDIA ==='
nvidia-smi 2>&1
echo '=== SERVICES / KERNEL (latest 3000 lines) ==='
journalctl -b -n 3000 --no-pager 2>&1
echo '=== DOCKER / WOLF (latest 3000 lines) ==='
docker ps -a 2>&1
docker logs --tail 3000 wolf 2>&1
'''.replace('LABEL', "'"+label+"'")
        text = capture(folder, 'guest.log', ['ssh', '-F', '/dev/null', '-o', 'BatchMode=yes',
                       '-o', 'ConnectTimeout=5', '-o', 'ConnectionAttempts=1', '-o',
                       'StrictHostKeyChecking=accept-new', '-o',
                       'UserKnownHostsFile='+str(folder.parent.parent/f'known_hosts.{info["id"]}'),
                       '-p', str(port), 'root@'+host, command], 20)
        if '=== BOOTSTRAP' in text: return
    write(folder/'guest-unavailable.txt', 'Guest logs unavailable: no identity-verified SSH endpoint responded.\n')


def diagnose(reason, provider, guest_log, info=None):
    info = info or {}
    status = '\n'.join(str(info[key]) for key in ('status_msg', 'status_message', 'error_msg', 'error', 'message') if info.get(key))
    if info.get('actual_status') != 'running' and re.search(r'GPU error, unable to start instance', status, re.I):
        return dict(category='provider_gpu', stage='Vast GPU preparation failed',
                    cause='Vast explicitly reported a GPU preparation error. The underlying passthrough/driver reason is not exposed.',
                    evidence=status)
    # Historical provisioning messages cannot diagnose a later client/guest failure.
    if info.get('actual_status') == 'running':
        provider = ''
    text = reason+'\n'+provider+'\n'+guest_log
    if reason.startswith('Boot wait paused:'):
        return dict(category='waiting', stage='Boot watcher paused',
                    cause='The local waiting budget expired or status was unavailable. VM failure is not confirmed; reconnect can resume.',
                    evidence=reason)
    rules = [
        ('provider_gpu', r'GPU error, unable to start instance', 'Vast GPU preparation failed',
         'Vast explicitly reported a GPU preparation error. The underlying passthrough/driver reason is not exposed.'),
        ('driver_mismatch', r'(?:Failed to initialize NVML: Driver/library version mismatch|NVRM: API mismatch)',
         'NVIDIA driver/library mismatch', 'Loaded NVIDIA driver and userspace libraries do not match.'),
        ('provider_domain', r"Domain not found: no domain with matching name[^\n]*", 'Guest VM missing',
         'Vast could not find its guest VM. This is a symptom; why guest creation failed is unknown.'),
        ('guest_permissions', r'(?:PermissionError:|Permission denied:)[^\n]*', 'Guest permission failure',
         'The logged file operation was denied; ownership/mount details must be checked in guest.log.'),
        ('client_libraries', r'(?:symbol lookup error:|error while loading shared libraries:)[^\n]*',
         'Local Moonlight libraries', 'The local Moonlight process could not load compatible libraries; VM failure is not established.'),
    ]
    for category, pattern, stage, cause in rules:
        match = re.search(pattern, text, re.I)
        if match: return dict(category=category, stage=stage, cause=cause, evidence=match.group(0))
    if 'did not reach running' in reason:
        return dict(category='provider_timeout', stage='Vast provisioning timeout',
                    cause='Vast did not confirm guest boot before the deadline. Underlying cause unknown.', evidence=reason)
    errors = [line for line in text.splitlines() if re.search(r'Traceback|\[VASTGAME\] (ERROR|FAILURE)|Error:|Assertion', line)]
    return dict(category='unknown', stage='Startup or client failure',
                cause='No confirmed root cause in the available logs. Inspect the evidence and timeline.',
                evidence='\n'.join(errors[:12]) or reason)


def record_failure(state, info, result):
    if result['category'] != 'provider_gpu': return
    machine = info.get('machine_id'); label = info.get('label'); image = info.get('image_uuid') or info.get('image')
    if machine is None or not label: return
    with (state/'host_history.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        history_path = state/'host_history.json'
        history = json.loads(history_path.read_text()) if history_path.exists() else {}
        if not isinstance(history, dict): raise ValueError('Invalid host history; existing file preserved')
        item = history.setdefault(f'machine:{machine}', {})
        failures = item.setdefault('provisioning_failures', [])
        if any(f['instance'] == str(info['id']) for f in failures): return
        failures.append(dict(instance=str(info['id']), label=label, image=image, time=time.time(),
                             category=result['category']))
        item['provisioning_failures'] = failures[-20:]
        json_write(state/'host_history.json', history)


def failure(state, folder, info, reason, ip=''):
    print('Collecting failure evidence (bounded probes; VM unchanged)...', flush=True)
    with ThreadPoolExecutor(max_workers=3) as pool:
        provider_job = pool.submit(capture, folder, 'vast.log',
                                   ['vastai', 'logs', str(info['id']), '--tail', '20000'], 20)
        daemon_job = pool.submit(capture, folder, 'vast-daemon.log',
                                 ['vastai', 'logs', str(info['id']), '--tail', '20000', '--daemon-logs'], 20)
        guest_job = pool.submit(guest, folder, info, ip)
        provider = provider_job.result(); daemon = daemon_job.result(); guest_job.result()
    local = state/'moonlight.log'
    if local.exists():
        with local.open('rb') as stream:
            stream.seek(max(0, local.stat().st_size-LIMIT))
            write(folder/'moonlight.log', stream.read(LIMIT).decode(errors='replace'))
    guest_text = '\n'.join(path.read_text() for path in folder.iterdir()
                           if path.name == 'guest.log' or path.name.startswith('http-'))
    client_text = '\n'.join(path.read_text() for path in folder.iterdir()
                            if path.name in ('moonlight.log', 'client-startup.log'))
    startup = (folder/'vast-startup.log').read_text() if (folder/'vast-startup.log').exists() else ''
    result = diagnose(reason, provider+'\n'+daemon+'\n'+startup, guest_text+'\n'+client_text, info)
    evidence_sources = ['instance.json', 'vast-startup.log', 'vast.log', 'vast-daemon.log', 'guest.log',
                        'http-bootstrap.log', 'http-game.log', 'moonlight.log', 'client-startup.log']
    result['evidence_files'] = [name for name in evidence_sources if (folder/name).exists()
                                and result['evidence'] in (folder/name).read_text()]
    result.update(instance=str(info['id']), machine=info.get('machine_id'), image=info.get('image_uuid') or info.get('image'),
                  reason=redact(reason), collected=datetime.datetime.now(datetime.timezone.utc).isoformat())
    try: record_failure(state, info, result)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result['history_error'] = str(exc)
    history = read(state/'host_history.json')
    machines = {key for key, value in history.items() if key.startswith('machine:') and any(
        f.get('category') == 'provider_gpu' and f.get('image') == result['image'] and time.time()-f['time'] < 86400
        for f in value.get('provisioning_failures', []))} if result['image'] else set()
    result['shared_image_warning'] = len(machines) >= 2
    json_write(folder/'summary.json', result)
    timeline = []
    for line in (folder/'timeline.jsonl').read_text().splitlines():
        row = json.loads(line)
        status = row['instance'].get('actual_status') or 'unknown'
        if not timeline or timeline[-1][1] != status: timeline.append((row['time'], status))
    first_event = datetime.datetime.fromisoformat(timeline[0][0]).timestamp()
    game_id = read(folder/'game.json').get('game')
    crashes = [str(p) for p in (state/'crashes').glob('session-*') if p.is_dir()
               and p.stat().st_mtime >= first_event and read(p/'session.json').get('game_id') == game_id]
    json_write(folder/'crashpad-references.json', dict(sessions=crashes,
               note='Local crash context only; binary dumps are not copied or uploaded.'))
    summary = (f'Failed: {result["stage"]}\nInstance: {result["instance"]} | Machine: {result["machine"]}\n'
               f'Cause: {result["cause"]}\nEvidence: {result["evidence"]}\nTrigger: {reason}\n'
               f'Evidence files: {", ".join(result["evidence_files"]) or "watcher trigger only"}\n'
               'Sequence: '+ ' -> '.join(f'{stamp} {status}' for stamp, status in timeline)+'\n'
               'Limits: provider logs up to 20000 lines / 16 MiB; guest journal and container logs are bounded. '
               'Collection failures are saved alongside logs. Crashpad cannot diagnose host provisioning.\n')
    if result['shared_image_warning']:
        summary += 'Warning: multiple machines failed with this image within 24 hours. Check template/launch compatibility; host blame is unconfirmed.\n'
    if 'history_error' in result: summary += 'Host history update failed: '+result['history_error']+'\n'
    write(folder/'summary.txt', summary)
    write(state/'latest-report', str(folder)+'\n')
    print(redact(summary.split('Limits:')[0]).strip())
    if result['shared_image_warning']: print(summary.split('Warning:')[1].strip())
    print('Report: '+str(folder))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('event', 'failure', 'log', 'client'))
    parser.add_argument('state', type=Path)
    parser.add_argument('instance')
    parser.add_argument('--game', default='')
    parser.add_argument('--reason', default='')
    parser.add_argument('--ip', default='')
    args = parser.parse_args()
    if not args.instance.isdigit(): raise ValueError('Invalid instance ID')
    os.umask(0o077)
    folder = args.state/'reports'/args.instance
    if args.mode in ('log', 'client'):
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = folder/('vast-startup.log' if args.mode == 'log' else 'client-startup.log')
        text = redact(sys.stdin.read(LIMIT))
        if path.exists() and path.stat().st_size >= LIMIT: return
        with path.open('a') as output:
            output.write('\n=== '+datetime.datetime.now(datetime.timezone.utc).isoformat()+' ===\n'+text)
        path.chmod(0o600); folder.chmod(0o700)
        return
    info = json.load(sys.stdin)
    if str(info.get('id')) != args.instance: raise ValueError('Report instance identity mismatch')
    event(folder, info, args.game)
    if args.mode == 'failure': failure(args.state, folder, info, args.reason, args.ip)


if __name__ == '__main__':
    main()
