#!/usr/bin/env python3
# Register and supervise the selected game inside Wolf's Lutris container.
import json
import fcntl
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import traceback
from compatibility import nvidia_ngx_enabled, wine_config


def validate(m):
    if m.get('schema') != 1 or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', m.get('id', '')):
        raise ValueError('Invalid game manifest schema or ID')
    for field in ('executable', 'working_dir'):
        value = m['game'].get(field, '')
        if not isinstance(value, str) or '\x00' in value or '\\' in value or Path(value).is_absolute() or '..' in Path(value).parts:
            raise ValueError('Unsafe game path: ' + field)
    if not m['game'].get('executable'):
        raise ValueError('Missing executable')
    args = m['game'].get('arguments', [])
    env = m.get('environment', {})
    if not isinstance(args, list) or not all(isinstance(a, str) and '\x00' not in a for a in args):
        raise ValueError('Arguments must be a list of strings')
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise ValueError('Environment must map strings to strings')
    if m.get('runner', {}).get('type', 'wine') != 'wine':
        raise ValueError('Only Wine games are supported by this launcher')
    package = m.get('package', {})
    for field in ('archive', 'checksum'):
        if field in package:
            if not re.fullmatch(r'games/' + re.escape(m['id']) + r'/[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+', package[field]):
                raise ValueError('Unsafe package path: ' + field)
    nvidia_ngx_enabled(m)
    return m


def config(m):
    validate(m)
    gid = m['id']
    wine, env = wine_config(m)
    # The Vulkan layer records actual game presents without a second visible HUD.
    # HOME is shared with the Steam Runtime container; /profiles may not be.
    performance = str(Path.home() / '.local/state/vastgame/performance' / gid)
    env.setdefault('MANGOHUD', '1')
    env.setdefault('MANGOHUD_CONFIG', 'no_display,autostart_log=1,log_interval=1000,log_duration=0,'
                   'permit_upload=0,output_folder=' + performance)
    return {'game': {'exe': f'/games/{gid}/' + m['game']['executable'],
                     'working_dir': f'/games/{gid}/' + m['game'].get('working_dir', ''),
                     'prefix': f'/prefixes/{gid}',
                     'arch': 'win64' if 'proton' in m.get('runner', {}).get('version', 'ge-proton').lower() else 'auto',
                     'args': shlex.join(m['game'].get('arguments', []))},
            'wine': wine,
            'system': {'env': env, 'prefix_command': '/usr/bin/python3 /opt/vastgame/game_state.py launch ' + gid}}


def lutris_api():
    # Use the installed Lutris schema and paths, not a hand-built SQLite schema.
    from lutris import settings
    # GOW installs the Lutris assets outside its Python package directory.
    try:
        import lutris.util.datapath as datapath
        if Path('/usr/share/lutris').is_dir():
            datapath.get = lambda: '/usr/share/lutris'
    except ImportError:
        pass
    from lutris.startup import init_lutris
    from lutris.database import games
    return settings, init_lutris, games


def register(m, preparing=False):
    settings, init_lutris, games = lutris_api()
    init_lutris()
    cfg = config(m)
    exe = Path(cfg['game']['exe'])
    # Setup runs cmd.exe while the immutable game package is still downloading.
    # Real launches always require the restored executable and working directory.
    if not preparing and not exe.is_file():
        raise FileNotFoundError(f'Configured executable is missing: {exe}')
    if not preparing and not Path(cfg['game']['working_dir']).is_dir():
        raise FileNotFoundError('Configured working directory is missing')
    Path(cfg['game']['prefix']).mkdir(parents=True, exist_ok=True)
    key = 'vastgame-' + m['id']
    # JSON is a YAML subset; preserves quotes, spaces, and all arguments safely.
    dest = Path(settings.GAME_CONFIG_DIR) / (key + '.yml')
    dest.write_text(json.dumps(cfg, indent=2))
    game_id = games.add_or_update(name=m.get('name', m['id']), slug=key, runner='wine',
                                  directory=str(exe.parent), installed=1, configpath=key)
    print(f'Registered Lutris ID {game_id}: {exe}', flush=True)
    return str(game_id)


def process_seen(exe, prefix, proc=Path('/proc')):
    # Observe the exact executable and prefix rather than the Lutris window.
    for p in proc.glob('[0-9]*'):
        try:
            args = (p / 'cmdline').read_bytes().split(b'\0')
            environment = (p / 'environ').read_bytes().split(b'\0')
            correct_prefix = ('WINEPREFIX=' + prefix).encode() in environment
            for raw in args:
                arg = raw.decode(errors='replace').replace('\\', '/')
                if arg.lower().startswith('z:'):
                    arg = arg[2:]
                if arg == exe or (correct_prefix and arg.rsplit('/', 1)[-1].lower() == Path(exe).name.lower()):
                    return True
        except (OSError, PermissionError):
            continue
    return False


def run():
    root = Path('/vastgame-status')
    session = json.loads((root / 'session.json').read_text())
    gid = session['game_id']
    logdir = Path('/profiles') / gid / 'logs'
    logdir.mkdir(parents=True, exist_ok=True)
    logfile = logdir / ('launch-' + time.strftime('%Y%m%dT%H%M%S') + '.log')
    # Publish only a bounded log tail on the tailnet-only status endpoint.
    log = logfile.open('a', buffering=1)
    os.dup2(log.fileno(), 1)
    os.dup2(log.fileno(), 2)
    (root / 'game.log').write_text('')

    def status(state, action, quiet=False, **extra):
        record = dict(session, state=state, action=action, updated=time.time(), **extra)
        tmp = root / ('launch.' + str(os.getpid()) + '.tmp')
        tmp.write_text(json.dumps(record))
        tmp.replace(root / 'launch.json')
        if not quiet:
            print(action, flush=True)

    child = None
    collector = None
    launch_lock = None
    try:
        launch_lock = (Path('/profiles') / gid / 'state.lock').open('a')
        fcntl.flock(launch_lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        if (root / 'stopping').exists():
            raise RuntimeError('Final backup in progress; game launch blocked')
        Path('/shaders/' + gid + '/cache').mkdir(parents=True, exist_ok=True)
        status('starting', 'Registering game in Lutris')
        m = validate(json.loads((Path('/profiles') / gid / 'manifest.json').read_text()))
        if m['id'] != gid:
            raise ValueError('Session and manifest IDs differ')
        from prepare_game import require_ready
        require_ready(m)
        game_id = register(m)
        cfg = config(m)
        from telemetry import Collector
        try:
            collector = Collector(gid, m['game']['executable']).start()
        except Exception as exc:
            print('Performance telemetry unavailable: ' + str(exc), flush=True)
        status('starting', 'Launching game through the prepared Lutris environment')
        child = subprocess.Popen(['lutris', '-d', 'lutris:rungameid/' + game_id], stdout=log, stderr=log)
        launch_lock.close(); launch_lock = None
        start = time.monotonic()
        seen_at = None
        confirmed = False
        timeout = int(os.environ.get('VASTGAME_LAUNCH_TIMEOUT', '600'))
        while True:
            seen = process_seen(cfg['game']['exe'], cfg['game']['prefix'])
            now = time.monotonic()
            if seen:
                if seen_at is None:
                    seen_at = now
                if not confirmed and now - seen_at >= 5:
                    confirmed = True
                    status('running', 'Configured game process detected; rendering is not verified')
                elif confirmed:
                    status('running', 'Configured game process detected; rendering is not verified', quiet=True)
            elif seen_at is not None:
                if not confirmed:
                    raise RuntimeError('Game process exited within five seconds; inspect the launch log')
                status('exited', 'Game process exited; see launch log for its output')
                return 0
            if child.poll() is not None and not seen:
                raise RuntimeError(f'Lutris exited with code {child.returncode} before the game process was detected')
            if not confirmed and now - start > timeout:
                raise TimeoutError(f'No game process detected after {timeout}s; Lutris may be waiting for a download or dialog')
            # Publish a bounded log tail without exposing other profile contents.
            with logfile.open('rb') as inp:
                inp.seek(max(0, logfile.stat().st_size - 65536))
                (root / 'game.log').write_bytes(inp.read())
            time.sleep(1)
    except Exception as exc:
        traceback.print_exc()
        status('error', str(exc))
        return 1
    finally:
        if collector is not None:
            collector.stop.set()
        if launch_lock is not None:
            launch_lock.close()
        log.flush()
        with logfile.open('rb') as inp:
            inp.seek(max(0, logfile.stat().st_size - 65536))
            (root / 'game.log').write_bytes(inp.read())
        # Do not kill a running game on a diagnostic timeout; keep the VM available.


if __name__ == '__main__':
    sys.exit(run())
