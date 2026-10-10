"""Stream redacted engine output; keep shutdown tied to this launch's exact VM."""
import fcntl
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time
import shutil
import urllib.request
import ipaddress
from failure_report import redact, json_write
from startup_progress import milestone
import session_history

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / 'bin/vastgame'
STATE = Path(os.environ.get('XDG_STATE_HOME', Path.home() / '.local/state')) / 'vastgame/desktop'
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
MARKER = '[VASTGAME_DESKTOP]'
ERROR_MARKER = '[VASTGAME_ERROR]'
last_error = None


def emit(kind, **data):
    try:
        print(json.dumps(dict(type=kind, **data)), flush=True)
    except BrokenPipeError:
        pass  # Closing the UI never destroys or cancels a paid VM.


def phase(line):
    for fragment, name in (
        ('Stage 1/3', 'Creating rig'), ('Allocating host', 'Allocating host'),
        ('Preparing VM image', 'Preparing image'), ('Booting VM', 'Booting rig'),
        ('Instance created:', 'Booting rig'), ('Stage 2/3', 'Connecting Tailscale'),
        ('Tailscale online:', 'Preparing runtime'), ('| RESTORE |', 'Preparing runtime'),
        ('| DRIVE |', 'Restoring game and saves'), ('| DOCKER |', 'Starting streaming server'),
        ('Restore complete;', 'Starting game'), ('CLOUD GAMING READY', 'Starting game'),
        ('Streaming ', 'Starting Moonlight'), ('Destroying Vast instance', 'Shutting down rig'),
        ('Closing the game before', 'Closing game'), ('Game ignored its close request', 'Closing game'),
        ('Final Google Drive', 'Backup verified'), ('Game never started;', 'Shutting down rig'),
        ('Game process detected.', 'Game running'), ('Final backup', 'Backing up saves'), ('Backing up saves', 'Backing up saves')):
        if fragment in line:
            return name
    return None


def birth(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
    except (OSError, IndexError):
        return ''


def update_job(folder, **changes):
    # Launch and shutdown can finish together; a stopped job must stay stopped.
    with (folder / 'job.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = folder / 'job.json'
        record = json.loads(path.read_text())
        if record.get('force_shutdown') and not changes.get('force_shutdown') and not changes.get('stopped'):
            # A canceled creation may still return its rental ID; preserve identity, never revive its state.
            identity = {}
            if changes.get('creation_requested') is True: identity['creation_requested'] = True
            instance = changes.get('instance_id')
            if record.get('instance_id') is None and isinstance(instance, str) and re.fullmatch(r'[0-9]+', instance): identity['instance_id'] = instance
            changes = dict(identity, force_shutdown=True) if identity else {}
        if not record.get('stopped') and (not record.get('force_shutdown') or changes.get('force_shutdown') or changes.get('stopped')):
            if changes.get('stopped'): changes.setdefault('ended_at', int(time.time() * 1000))
            record.update(changes)
            json_write(path, record)
        try:
            session_history.archive_job(path)
            session_history.job_update(record)
        except (OSError, ValueError, TypeError): emit('log', line='Warning: session history could not be saved; rig operation continues.')
        return record


def run(args, folder, record=None):
    process = None
    interrupted = False
    def interrupt(_signum, _frame):
        nonlocal interrupted
        interrupted = True
        if process is not None and process.poll() is None:
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
    # Install cancellation before spawning, including a force click during startup.
    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        process = subprocess.Popen([str(BIN), *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, start_new_session=True,
                                   env=dict(os.environ, VASTGAME_DESKTOP='1', PYTHONUNBUFFERED='1', VASTAI_NO_UPDATE_CHECK='1',
                                            VASTGAME_LAUNCH_LABEL=record['label'] if record else ''))
        if record is not None:
            record.update(update_job(folder, engine_pid=process.pid, engine_birth=birth(process.pid)))
        latest = json.loads((folder/'job.json').read_text())
        superseded = ((args[0] == 'stop' and '--force' not in args and latest.get('force_shutdown')) or
                      (args[0] in ('start', 'connect') and (latest.get('force_shutdown') or latest.get('stopped'))))
        if interrupted or superseded: interrupt(None, None)
    except BaseException:
        if process is not None: interrupt(None, None)
        signal.signal(signal.SIGTERM, previous)
        raise
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    buffer = b''
    secret = False
    last_phase = ''
    log = folder / 'events.jsonl'
    history = session_history.LogWriter(json.loads((folder/'job.json').read_text()).get('label'), phase)
    history_failed = False
    def output(raw):
        nonlocal secret, last_phase, history_failed
        global last_error
        line = ANSI.sub('', raw.decode(errors='replace')).rstrip()
        if not line.strip():
            return
        if line.startswith('[VASTGAME_PROGRESS]') and record is not None:
            data = json.loads(line[len('[VASTGAME_PROGRESS]'):])
            if isinstance(data, dict) and isinstance(data.get('stages'), list) and len(data['stages']) == 5:
                record.update(update_job(folder, progress=data))
                emit('progress', progress=data)
            return
        if line == '[VASTGAME_CREATE_REQUESTED]' and record is not None:
            record.update(update_job(folder, creation_requested=True))
            return
        if line == '[VASTGAME_GAME_REQUESTED]' and record is not None:
            record.update(update_job(folder, game_requested=True))
            return
        if line.startswith(ERROR_MARKER):
            error = json.loads(line[len(ERROR_MARKER):])
            if isinstance(error, dict) and isinstance(error.get('code'), str) and isinstance(error.get('message'), str):
                last_error = error
                emit('error', error=error)
        if line.startswith('ERROR:') and last_error is None:
            last_error = dict(code='ENGINE_ERROR', message=redact(line[6:].strip())[:4096])
            emit('error', error=last_error)
        if line.startswith(MARKER) and record is not None:
            data = json.loads(line[len(MARKER):])
            if record.get('instance_id') is None and re.fullmatch(r'[0-9]+', data.get('instance_id', '')) and re.fullmatch(r'vastgame-[0-9]+', data.get('label', '')):
                record.update(update_job(folder, instance_id=data['instance_id'], label=data['label']))
                if record['instance_id'] is not None:
                    emit('instance', instance_id=record['instance_id'])
            return
        if '-----BEGIN ' in line and 'PRIVATE KEY-----' in line:
            secret = True
            line = '[private key redacted]'
        elif secret:
            if '-----END ' in line and 'PRIVATE KEY-----' in line: secret = False
            return
        line = redact(line).replace(str(Path.home()), '~')
        if not history_failed:
            try: history.append(line)
            except (OSError, ValueError, TypeError):
                history_failed = True
                emit('log', line='Warning: session logs could not be archived; rig operation continues.')
        line = line[:4096]
        entry = dict(type='log', line=line, time=int(time.time() * 1000))
        if log.exists() and log.stat().st_size >= 2 * 1024 * 1024:
            log.replace(folder / 'previous.jsonl')
        with log.open('a') as file:
            file.write(json.dumps(entry) + '\n')
        log.chmod(0o600)
        emit('log', line=line, time=entry['time'])
        name = phase(line)
        if name and name != last_phase:
            last_phase = name
            if record is not None:
                changes = dict(phase=name, progress=milestone(record.get('progress'), name))
                if name == 'Game running': changes.update(game_running=True, game_observed_at=time.time())
                record.update(update_job(folder, **changes))
            emit('status', phase=name, progress=record.get('progress') if record else None)
    try:
        while True:
            if not selector.select(0.2):
                if process.poll() is not None:
                    # The launcher closes inherited pipes before leaving Moonlight running.
                    break
                continue
            block = os.read(process.stdout.fileno(), 8192)
            if not block: break
            buffer += block
            while b'\n' in buffer or b'\r' in buffer:
                split = re.search(b'[\r\n]', buffer)
                output(buffer[:split.start()])
                buffer = buffer[split.end():]
            if len(buffer) > 8192:
                output(buffer[:8192]); buffer = b''
        if buffer: output(buffer)
        return process.wait(), interrupted
    finally:
        signal.signal(signal.SIGTERM, previous)
        selector.close()
        process.stdout.close()


def launch(job, game, offer, price, machine="0", started_ms=None):
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', game) or not offer.isdecimal() or int(offer) <= 0:
        raise ValueError('Invalid game or selected rig')
    if not machine.isdecimal(): raise ValueError('Invalid machine ID')
    ceiling = float(price)
    if not math.isfinite(ceiling) or ceiling < 0:
        raise ValueError('Invalid selected price')
    now = int(time.time() * 1000)
    started = now if started_ms is None else int(started_ms)
    if started <= 0 or started > now + 60000:
        raise ValueError('Invalid session start time')
    folder = STATE / job
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    prune_jobs()
    record = dict(job=job, game=game, pid=os.getpid(), birth=birth(os.getpid()), instance_id=None,
                  label=session_history.new_label(), creation_requested=False, game_requested=False, started_at=started)
    json_write(folder / 'job.json', record)
    try: session_history.begin(record['label'], game, started, job)
    except (OSError, ValueError, TypeError): emit('log', line='Warning: session history could not be saved; rig operation continues.')
    emit('status', phase='Checking selected rig')
    code, interrupted = run(['start', game, '--offer-id', str(int(offer)), '--machine-id', machine, '--max-price', format(ceiling, '.12f'), '--yes'], folder, record)
    if record.get('creation_requested') and record.get('instance_id') is None:
        emit('error', error=dict(code='CREATION_UNCONFIRMED', message='Rental result unknown. Refresh status before starting another rig'))
    record = update_job(folder, finished=True, success=code == 0, phase='Game ready' if code == 0 else (last_error or {}).get('message', 'Launch failed'))
    emit('finished', ok=code == 0, phase='Ready' if code == 0 else 'Watcher stopped; VM retained' if interrupted else (last_error or {}).get('message', 'Launch failed – check Logs'), instance_id=record['instance_id'])


def interrupt_worker(record, job, prefix='', mode='launch'):
    pid, expected = record.get(prefix+'pid'), record.get(prefix+'birth')
    if type(pid) is not int or not expected or birth(pid) != expected: return
    descriptor = None
    try:
        descriptor = os.pidfd_open(pid)
        if birth(pid) != expected: return
        command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
        script = next((index for index, part in enumerate(command) if part.endswith(b'/desktop_launch.py')), None)
        if script is None: return
        arguments = [part for part in command[script+1:] if part]
        if arguments[:2] != [mode.encode(), job.encode()]: return
        if mode == 'stop' and len(arguments) != 2: return
        signal.pidfd_send_signal(descriptor, signal.SIGTERM)
    except OSError:
        emit('log', line='Could not interrupt the owned worker; exact VM shutdown will still be attempted.')
    finally:
        if descriptor is not None: os.close(descriptor)


def stop(job, force=False):
    folder = STATE / job
    record = json.loads((folder / 'job.json').read_text())
    instance, label = record.get('instance_id'), record.get('label')
    if record.get('job') != job or not isinstance(instance, str) or not re.fullmatch(r'[0-9]+', instance) or not isinstance(label, str) or not re.fullmatch(r'vastgame-[0-9]+', label):
        raise ValueError('VM identity is not available yet. Wait for creation before shutdown')
    if force:
        record = update_job(folder, force_shutdown=True, shutdown_requested=True, phase='Shutting down rig')
        interrupt_worker(record, job, 'stop_', 'stop')
    else:
        record = update_job(folder, stop_pid=os.getpid(), stop_birth=birth(os.getpid()), shutdown_requested=True)
        if record.get('force_shutdown'):
            emit('finished', ok=False, phase='Shutdown superseded by force request', instance_id=instance)
            return
    interrupt_worker(record, job)
    interrupt_worker(record, job, mode='connect')
    emit('status', phase='Shutting down rig' if force else 'Checking rig')
    args = ['stop', '--force', '--instance-id', instance, '--label', label] if force else ['stop', '--instance-id', instance, '--label', label, '--startup-job', job]
    code, _ = run(args, folder)
    latest = json.loads((folder/'job.json').read_text())
    if not force and latest.get('force_shutdown'): return
    if code == 0:
        update_job(folder, stopped=True, finished=True, success=True, instance_id=None, game_running=False, phase='Rig shut down')
    else:
        update_job(folder, finished=True, success=False, phase='Shutdown failed; VM retained', **({'force_shutdown': True} if force else {}))
    emit('finished', ok=code == 0, phase='Rig shut down' if code == 0 else 'Shutdown failed; VM retained', instance_id=None if code == 0 else instance)


def connect(job):
    folder = STATE / job
    record = json.loads((folder / 'job.json').read_text())
    instance, label = record.get('instance_id'), record.get('label')
    if record.get('job') != job or record.get('stopped') or not isinstance(instance, str) or not re.fullmatch(r'[0-9]+', instance) or not isinstance(label, str) or not re.fullmatch(r'vastgame-[0-9]+', label):
        raise ValueError('VM identity is not available. Refresh before connecting')
    if record.get('force_shutdown'):
        raise ValueError('Force shutdown unconfirmed. Retry X before connecting')
    if not record.get('finished') or alive(record) or alive(record, True):
        raise ValueError('Wait for the current rig operation to finish before connecting')
    record = update_job(folder, pid=os.getpid(), birth=birth(os.getpid()), finished=False)
    if record.get('force_shutdown') or record.get('stopped'):
        raise ValueError('Shutdown superseded reconnect')
    code = 1
    try:
        code, _ = run(['connect', '--instance-id', instance, '--label', label], folder, record)
    finally:
        record = update_job(folder, finished=True, success=code == 0, phase='Game running' if code == 0 else 'Connection failed; VM retained')
    emit('finished', ok=code == 0, phase=record['phase'], instance_id=record.get('instance_id'), game_running=bool(record.get('game_running')))


def watch(job):
    # inotify sleeps until the engine writes; Linux and the Windows WSL backend
    # share this path, with no idle polling or third-party watcher dependency.
    import ctypes
    import select
    def send(kind, **data):
        try: print(json.dumps(dict(type=kind, **data)), flush=True)
        except BrokenPipeError: raise SystemExit(0)  # A disconnected reader can exit without affecting the engine.
    folder = STATE/job
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.inotify_init1(os.O_CLOEXEC | os.O_NONBLOCK)
    if fd < 0: raise OSError('Cannot watch launch progress')
    offset, inode, last_phase, last_progress = 0, None, None, None
    initial = json.loads((folder/'job.json').read_text())
    process_fd = None
    if alive(initial):
        try: process_fd = os.pidfd_open(initial['pid'])
        except (OSError, AttributeError): pass
    try:
        if libc.inotify_add_watch(fd, os.fsencode(folder), 0x00000008 | 0x00000080 | 0x00000100) < 0:
            raise OSError('Launch progress folder unavailable')
        while True:
            record = json.loads((folder/'job.json').read_text())
            if record.get('job') != job: raise ValueError('Launch identity differs')
            log = folder/'events.jsonl'
            if log.exists():
                size = log.stat()
                if inode != size.st_ino or offset > size.st_size:
                    inode = size.st_ino
                    offset = max(0, size.st_size - 2*1024*1024)
                with log.open('rb') as file:
                    file.seek(offset)
                    data = file.read(2*1024*1024)
                    offset = file.tell()
                for line in data.splitlines()[-500:]:
                    try:
                        event = json.loads(line)
                        if event.get('type') == 'log' and isinstance(event.get('line'), str): send('log', line=event['line'][:4096], time=event.get('time'))
                    except (ValueError, TypeError): pass
            progress = record.get('progress')
            if progress != last_progress:
                send('progress', progress=progress)
                last_progress = progress
            phase_name = record.get('phase', 'Rig retained')
            running = bool(record.get('game_running', record.get('success', False)))
            if (phase_name, running) != last_phase:
                send('status', phase=phase_name, game_running=running)
                last_phase = (phase_name, running)
            if record.get('finished') or record.get('stopped'):
                send('finished', ok=bool(record.get('success')), phase=phase_name, instance_id=record.get('instance_id'), game_running=running)
                return
            if not alive(record):
                send('finished', ok=False, phase='Watcher ended; refresh status', instance_id=record.get('instance_id'), game_running=running)
                return
            ready, _, _ = select.select([fd] + ([process_fd] if process_fd is not None else []), [], [], None if process_fd is not None else 1)
            if fd in ready: os.read(fd, 65536)
    finally:
        os.close(fd)
        if process_fd is not None: os.close(process_fd)


def alive(record, engine=False):
    key = 'engine_' if engine else ''
    pid = record.get(key + 'pid')
    return type(pid) is int and bool(birth(pid)) and birth(pid) == record.get(key + 'birth')


def prune_jobs():
    # Only retired exact jobs are disposable; unresolved rental identities stay.
    retired = []
    for path in STATE.glob('*/job.json'):
        try:
            if path.parent.is_symlink() or not re.fullmatch(r'[a-f0-9]{32}', path.parent.name): continue
            record = json.loads(path.read_text())
            if not isinstance(record, dict): continue
            if record.get('stopped') and not alive(record) and not alive(record, True):
                retired.append((path.stat().st_mtime, path.parent))
        except (OSError, ValueError, TypeError): pass
    retired.sort(reverse=True)
    for index, (modified, folder) in enumerate(retired):
        age = time.time() - modified
        if age < 86400 or (index < 50 and age < 30 * 86400): continue
        try:
            with (folder/'job.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                record = json.loads((folder/'job.json').read_text())
                if not isinstance(record, dict): continue
                if record.get('stopped') and not alive(record) and not alive(record, True):
                    session_history.archive_job(folder/'job.json')
                    shutil.rmtree(folder)
        except (OSError, ValueError, TypeError): pass


def guest_state(record):
    # A Tailscale peer must present this exact launch label before its data is used.
    try:
        lookup = subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True, timeout=10)
        peers = json.loads(lookup.stdout).get('Peer', {})
        deadline = time.monotonic() + 6
        for peer in list(peers.values())[:100]:
            if time.monotonic() >= deadline: break
            if not peer.get('Online') or not any(str(peer.get(key, '')).startswith('vast-gaming') for key in ('HostName', 'DNSName')): continue
            for address in peer.get('TailscaleIPs', []):
                if time.monotonic() >= deadline: break
                if ipaddress.ip_address(address) not in ipaddress.ip_network('100.64.0.0/10'): continue
                base = f'http://{address}:48199/'
                try:
                    with urllib.request.urlopen(base+'instance-label', timeout=2) as reply:
                        if reply.read(128).decode().strip() != record['label']: continue
                    with urllib.request.urlopen(base+'launch.json', timeout=3) as reply: raw = reply.read(65537)
                    if len(raw) > 65536: continue
                    data = json.loads(raw)
                    if data.get('game_id') == record['game'] and data.get('state') in ('running', 'error', 'exited'):
                        return data['state']
                except (OSError, ValueError): continue
    except (OSError, ValueError, TypeError, AttributeError, subprocess.TimeoutExpired): pass
    return None


def current(job=None, rows=None):
    from game_catalog import library_summary
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'vastgame'
    prune_jobs()
    paths = [STATE/job/'job.json'] if job else list(STATE.glob('*/job.json'))
    paths = [path for path in paths if path.is_file()]
    if not paths: return None
    try: games = library_summary(config/'games', STATE.parent/'selected_game')['games']
    except (OSError, ValueError, TypeError): games = []
    if rows is None:
        rows = instance_rows()
    for path in sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True):
        try:
            record = json.loads(path.read_text())
            if not isinstance(record, dict): continue
            jid, gid, label = record.get('job', ''), record.get('game', ''), record.get('label', '')
            if not re.fullmatch(r'[a-f0-9]{32}', jid) or record.get('stopped'): continue
            instance = record.get('instance_id')
            # Older records may have an exact instance ID but never a pre-create label.
            if not isinstance(label, str) or not re.fullmatch(r'vastgame-[0-9]+', label): continue
            matches = [row for row in rows if isinstance(row, dict) and row.get('label') == label and
                       (instance is None or str(row.get('id')) == instance)]
            if len(matches) > 1: raise ValueError('Ambiguous rental identity; check Vastgame status')
            active = alive(record) or alive(record, True)
            if not matches:
                if active:
                    status, phase_name = 'starting', record.get('phase', 'Checking rig')
                else:
                    update_job(path.parent, stopped=True, finished=True, success=False, instance_id=None, game_running=False, phase='No rig found')
                    continue
            else:
                instance = str(matches[0]['id'])
                if not instance.isdecimal(): raise ValueError('Provider rental identity is invalid')
                if record.get('instance_id') is None: record = update_job(path.parent, instance_id=instance)
                status = 'starting' if active and not record.get('finished') else 'ready' if record.get('success') else 'error'
                phase_name = record.get('phase', 'Rig retained') if active or record.get('finished') else 'Watcher ended; rig retained'
            observed = guest_state(record) if matches and not active else None
            running = observed == 'running' if observed else bool(record.get('game_running', record.get('success', False)))
            if observed:
                status = 'ready' if running else 'error'
                phase_name = 'Game running' if running else 'Game exited' if observed == 'exited' else 'Game failed'
                update_job(path.parent, game_running=running, phase=phase_name, game_observed_at=time.time())
            if json.loads(path.read_text()).get('stopped'): continue
            game = next((game for game in games if game['id'] == gid), None)
            return dict(jobId=jid, gameId=gid, gameName=game['name'] if game else 'Game', instanceId=instance,
                        startedAt=record.get('started_at', int(label[9:]) // 1000000 if len(label[9:]) >= 18 else 0), endedAt=record.get('ended_at', 0),
                        phase=phase_name, status=status, shutdownRequested=bool(record.get('shutdown_requested')), gameRunning=running, stateFresh=observed is not None,
                        progress=record.get('progress'), observedAt=time.time() * 1000 if observed else record.get('game_observed_at', 0) * 1000)
        except (OSError, TypeError, KeyError, json.JSONDecodeError): continue
    return None


def instance_rows():
    try:
        lookup = subprocess.run(['vastai', 'show', 'instances', '--raw'], capture_output=True, text=True, timeout=15)
        if lookup.returncode or len(lookup.stdout) > 8*1024*1024: raise ValueError('Provider instance lookup failed')
        rows = json.loads(lookup.stdout)
        if not isinstance(rows, list): raise ValueError('Provider instance lookup failed')
        return rows
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        raise ValueError('Cannot verify retained rentals. Refresh status before starting another rig') from exc


if __name__ == '__main__':
    try:
        if sys.argv[1:2] == ['current']:
            requested = sys.argv[2] if len(sys.argv) == 3 else None
            if requested and not re.fullmatch(r'[a-f0-9]{32}', requested): raise ValueError('Invalid launch identity')
            try: print(json.dumps(dict(session=current(requested))))
            except (OSError, ValueError): print(json.dumps(dict(error=dict(code='SESSION_LOOKUP_FAILED', message='Cannot verify retained rentals. Refresh status before starting another rig'))))
            sys.exit(0)
        mode, job, *args = sys.argv[1:]
        if not re.fullmatch(r'[a-f0-9]{32}', job):
            raise ValueError('Invalid launch identity')
        STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        if mode == 'launch' and len(args) in (4, 5): launch(job, *args)
        elif mode == 'stop' and (not args or args == ['--force']): stop(job, force=bool(args))
        elif mode == 'connect' and not args: connect(job)
        elif mode == 'watch' and not args: watch(job)
        else: raise ValueError('Invalid desktop operation')
    except (OSError, ValueError, TypeError, KeyError) as exc:
        emit('log', line=redact(str(exc))[:4096])
        emit('finished', ok=False, phase='Operation failed')
        sys.exit(1)
