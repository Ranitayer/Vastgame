#!/usr/bin/env python3
"""Small verified per-game snapshots; no game binaries or whole Wine prefixes."""
import argparse
import fcntl
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def relative(value):
    if not isinstance(value, str) or not value or '\\' in value or '\x00' in value:
        raise ValueError('Invalid state path')
    p = Path(value)
    if p.is_absolute() or '..' in p.parts or str(p) != value or value == '.':
        raise ValueError('Unsafe state path: ' + value)
    return p


def gid_check(gid):
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', gid):
        raise ValueError('Invalid game ID')


def runner_builds(gid, container=False):
    root = Path('/var/lutris') if container else Path('/srv/gaming/lutris') / gid
    builds = {}
    for kind, relative_dir in [('wine', 'share/runners/wine'), ('proton', 'share/runners/proton'), ('dxvk', 'share/runtime/dxvk'), ('vkd3d', 'share/runtime/vkd3d'), ('umu-proton', 'home/.local/share/Steam/compatibilitytools.d'), ('umu-tools', 'home/.local/share/umu/compatibilitytools')]:
        directory = root / relative_dir
        builds[kind] = []
        for build in sorted(directory.iterdir()) if directory.exists() else []:
            if not build.is_dir(): continue
            versions = {}
            for file in sorted(build.rglob('*')):
                if file.is_file() and file.name.lower() in ('version', 'version.json', 'toolmanifest.vdf', 'compatibilitytool.vdf', 'd3d11.dll', 'd3d12.dll', 'dxgi.dll'):
                    versions[file.relative_to(build).as_posix()] = digest(file)
            builds[kind].append(dict(name=build.name, versions=versions))
    return builds


def cache_context(m):
    try:
        gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=name,driver_version', '--format=csv,noheader'], text=True, stderr=subprocess.DEVNULL, timeout=20).strip() or None
    except (OSError, subprocess.SubprocessError):
        gpu = None
    if gpu is None:
        print('GPU identity unavailable; saves/configs will still persist. Shader caches will require a known matching GPU before reuse.', flush=True)
    return dict(gpu_driver=gpu, runner=m.get('runner', {}), builds=runner_builds(m['id']),
                game_version=m.get('version', 'v1'), package=m.get('package', {}).get('sha256', m.get('package', {}).get('parts', [])), schema=1)


def context_key(context):
    return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()


def cache_identity(m):
    return context_key(cache_context(m))


def roots(root, gid):
    return {base: Path(root) / folder / gid for base, folder in
            [('game', 'games'), ('prefix', 'prefixes'), ('saves', 'saves'), ('configs', 'configs'), ('shaders', 'shaders')]}


def state_entries(m, root, kind, include_fallback=True):
    gid_check(m['id'])
    policy = m.get('state', {})
    if not isinstance(policy, dict) or type(policy.get('stateless', False)) is not bool or not isinstance(policy.get(kind, []), list):
        raise ValueError('Invalid state policy')
    bases = roots(root, m['id'])
    entries = []
    for entry in m.get('state', {}).get(kind, []):
        if isinstance(entry, str):
            entry = dict(base='prefix', path=entry, required=kind == 'saves')
        if not isinstance(entry, dict) or entry.get('base') not in bases or type(entry.get('required', False)) is not bool:
            raise ValueError('Invalid state entry: ' + kind)
        relative(entry.get('path'))
        entries.append(entry)
    discovery = policy.get('discovery', {})
    if not isinstance(discovery, dict) or not isinstance(discovery.get('recipes', []), list):
        raise ValueError('Invalid save discovery policy')
    for recipe in discovery.get('recipes', []):
        if not isinstance(recipe, dict) or recipe.get('kind') not in ('saves', 'configs') or recipe.get('base') not in ('prefix', 'game'):
            raise ValueError('Invalid discovered state recipe')
        pattern = relative(recipe.get('pattern'))
        if str(pattern) in ('*', '**'):
            raise ValueError('Overbroad discovered state recipe')
        if recipe['kind'] != kind:
            continue
        base = bases[recipe['base']]
        count = 0
        for path in base.glob(str(pattern)):
            count += 1
            if count > 10000:
                raise ValueError('Discovered state pattern matched too many paths')
            if path.is_symlink() or not path.resolve().is_relative_to(base.resolve()):
                raise ValueError('Discovered state path escapes its root: ' + str(path))
            entries.append(dict(base=recipe['base'], path=path.relative_to(base).as_posix()))
    # Generic prefix user data is a safety net, not an assertion that every game's
    # custom save location can be inferred. Explicit manifest paths remain required.
    if kind == 'saves' and include_fallback:
        users = bases['prefix'] / 'drive_c/users'
        if users.exists():
            for user in sorted(users.iterdir()):
                if user.is_symlink():
                    continue
                for name in ('AppData', 'Documents', 'Saved Games', 'My Documents'):
                    p = user / name
                    if p.is_dir() and not p.is_symlink():
                        entries.append(dict(base='prefix', path=p.relative_to(bases['prefix']).as_posix()))
    if kind == 'configs' or (kind == 'saves' and (discovery.get('registry') or any(
            p.startswith('registry:HKEY_CURRENT_USER\\') for p in discovery.get('unsupported', [])))):
        for name in ('user.reg', 'userdef.reg'):
            if (bases['prefix'] / name).is_file():
                entries.append(dict(base='prefix', path=name))
    if kind == 'configs' and bases['game'].exists():
        for p in sorted(bases['game'].iterdir()):
            if p.is_file() and not p.is_symlink() and p.suffix.lower() in ('.ini', '.cfg'):
                entries.append(dict(base='game', path=p.name))
    if kind == 'shaders' and bases['game'].exists():
        for p in sorted(bases['game'].iterdir()):
            if p.is_file() and not p.is_symlink() and re.search(r'(shader|pipeline|dxvk|vkd3d).*\.(bin|cache[0-9]*|dxvk-cache|write)$', p.name, re.I):
                entries.append(dict(base='game', path=p.name))
    if kind == 'shaders':
        entries.append(dict(base='shaders', path='cache'))
    return entries


def save_coverage(m, root):
    policy = m.get('state', {})
    if policy.get('stateless', False):
        return 'stateless'
    discovery = policy.get('discovery', {})
    unsupported = [p for p in discovery.get('unsupported', []) if not p.startswith('registry:HKEY_CURRENT_USER\\')]
    if unsupported and not policy.get('saves'):
        raise ValueError('Save coverage incomplete: configure explicit state.saves for ' + ', '.join(unsupported))
    declared = bool(policy.get('saves'))
    recipes = [p for p in discovery.get('recipes', []) if p['kind'] == 'saves']
    base = roots(root, m['id'])
    matched = any(any(base[p['base']].glob(str(relative(p['pattern'])))) for p in recipes)
    registry = discovery.get('registry', []) + [p[9:] for p in discovery.get('unsupported', []) if p.startswith('registry:HKEY_CURRENT_USER\\')]
    if declared or matched or registry:
        return 'declared' if declared else 'catalog'
    raise ValueError('No save coverage confirmed: run vastgame saves <id> --title <exact title> or configure state.saves; VM retained')


def collect(m, root, kind, scoped=False):
    bases = roots(root, m['id'])
    files = {}
    for entry in state_entries(m, root, kind, include_fallback=not scoped):
        base = bases[entry['base']].resolve()
        path = base / relative(entry['path'])
        if not path.resolve().is_relative_to(base):
            raise ValueError('State path escapes its root: ' + str(path))
        if not path.exists():
            if entry.get('required', False):
                raise ValueError('Required state path missing: ' + str(path))
            continue
        candidates = [path] if path.is_file() else sorted(path.rglob('*'))
        found = 0
        for p in candidates:
            if p.is_symlink():
                # Wine creates document aliases. Never follow aliases outside roots.
                if not p.resolve().is_relative_to(base):
                    raise ValueError('State symlink escapes its root: ' + str(p))
                continue
            if p.is_dir():
                continue
            if not p.is_file() or not p.resolve().is_relative_to(base):
                raise ValueError('Unsafe state file: ' + str(p))
            if kind == 'saves' and any(part.lower() in ('dxvk', 'dxcache', 'glcache', 'd3dscache') for part in p.relative_to(base).parts):
                continue
            if p.name.lower() in ('nvngx.dll', '_nvngx.dll'):
                raise ValueError('Driver-specific DLLs cannot be persisted')
            name = entry['base'] + '/' + p.relative_to(base).as_posix()
            files[name] = dict(path=p, size=p.stat().st_size, sha256=digest(p))
            found += 1
        if entry.get('required') and not found:
            raise ValueError('Required state path is empty: ' + str(path))
    if kind == 'saves' and not files and not m.get('state', {}).get('stateless', False):
        raise ValueError('No save/user data found; configure state.saves or explicitly declare state.stateless')
    return files


def inventory(files):
    return {name: {k: v[k] for k in ('size', 'sha256')} for name, v in sorted(files.items())}


def archive(files, dest):
    with Path(dest).open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=1, mtime=0, filename='') as zipped:
        with tarfile.open(fileobj=zipped, mode='w|', format=tarfile.PAX_FORMAT) as tar:
            for name, item in sorted(files.items()):
                p = item['path']
                info = tarfile.TarInfo(name)
                info.size = item['size']; info.mode = 0o600
                with p.open('rb') as stream:
                    tar.addfile(info, stream)
                if p.stat().st_size != item['size'] or digest(p) != item['sha256']:
                    raise ValueError('State changed during snapshot: ' + str(p))


class Remote:
    def __init__(self, root='gdrive:VastGaming', config=None):
        self.root = root.rstrip('/')
        self.cmd = ['rclone'] + (['--config', config] if config else [])

    def run(self, *args, capture=False):
        return subprocess.check_output(self.cmd + list(args), text=True, timeout=1800) if capture else subprocess.run(self.cmd + list(args), check=True, timeout=1800)

    def read(self, path):
        return self.run('cat', self.root + '/' + path, capture=True)

    def list(self, path):
        return self.run('lsf', self.root + ('/' + path if path else ''), '--dirs-only', capture=True).splitlines()

    def upload(self, local, path):
        self.run('copyto', str(local), self.root + '/' + path, '--retries', '3', '--stats-one-line', '--stats', '5s')
        # Read back and verify actual bytes before any commit marker is published.
        with tempfile.TemporaryDirectory() as tmp:
            fetched = Path(tmp) / 'verify'
            self.download(path, fetched)
            if digest(local) != digest(fetched):
                raise ValueError('Remote verification failed: ' + path)

    def download(self, path, local):
        self.run('copyto', self.root + '/' + path, str(local), '--retries', '3')


def latest(remote, gid, allow_pending=False):
    gid_check(gid)
    if 'state/' not in remote.list('') or gid + '/' not in remote.list('state'):
        return None
    dirs = remote.list('state/' + gid)
    if 'snapshots/' not in dirs:
        if allow_pending and set(dirs) <= {'objects/', 'shaders/'}:
            return None
        raise ValueError('Legacy state exists without committed snapshots; migration required')
    names = sorted(remote.list('state/' + gid + '/snapshots'), reverse=True)
    for name in names:
        snap = name.rstrip('/')
        if not re.fullmatch(r'[0-9]{20}-[a-f0-9]{32}', snap):
            raise ValueError('Invalid snapshot name')
        path = 'state/' + gid + '/snapshots/' + snap + '/COMMITTED.json'
        # List files so interrupted uploads are skipped, but network errors propagate.
        files = remote.run('lsf', remote.root + '/state/' + gid + '/snapshots/' + snap, '--files-only', capture=True).splitlines()
        if 'COMMITTED.json' in files:
            result = json.loads(remote.read(path))
            if result.get('schema') != 1 or result.get('game_id') != gid or result.get('snapshot') != snap:
                raise ValueError('Invalid committed snapshot')
            return result
    if allow_pending:
        return None
    raise ValueError('Remote state contains no committed snapshot; refusing an empty restore')


def backup(m, root, remote, instance, cache_key, context=None, live=False):
    gid = m['id']; gid_check(gid)
    coverage = save_coverage(m, root)
    previous = latest(remote, gid, allow_pending=True)
    snapshot = '%020d-%s' % (time.time_ns(), uuid.uuid4().hex)
    record = dict(schema=1, game_id=gid, instance_id=str(instance), snapshot=snapshot,
                  coverage=coverage, previous=previous['snapshot'] if previous else None, game_version=m.get('version', 'v1'), artifacts=[])
    with tempfile.TemporaryDirectory() as tmp:
        for kind in ('saves', 'configs', 'shaders'):
            frozen_shader = None
            shader_deferred = False
            if live and kind == 'shaders':
                try:
                    files = collect(m, root, kind, scoped=True)
                    frozen_shader = Path(tmp) / 'shaders.tar.gz'
                    archive(files, frozen_shader)
                    if inventory(collect(m, root, kind, scoped=True)) != inventory(files):
                        raise ValueError('Shader cache changed during capture')
                except (OSError, ValueError) as error:
                    print('Shader checkpoint deferred: ' + str(error), flush=True)
                    files = {}; frozen_shader = None; shader_deferred = True
            else:
                files = collect(m, root, kind, scoped=live)
            inv = inventory(files)
            old = next((a for a in (previous or {}).get('artifacts', []) if a['kind'] == kind and a.get('cache_key') == (cache_key if kind == 'shaders' else None) and a['files'] == inv), None)
            if shader_deferred:
                old = next((a for a in (previous or {}).get('artifacts', []) if a['kind'] == kind and a.get('cache_key') == cache_key), None)
            if old:
                # Revalidate remote object before using an old receipt for destruction.
                fetched = Path(tmp) / kind
                remote.download(old['path'], fetched)
                if digest(fetched) != old['sha256']:
                    raise ValueError('Previous state object corrupted')
                record['artifacts'].append(old)
                print('Reused verified ' + kind, flush=True)
                continue
            dest = Path(tmp) / (kind + '.tar.gz')
            if frozen_shader is None:
                archive(files, dest)
            sha = digest(dest)
            path = 'state/' + gid + ('/shaders/' + cache_key if kind == 'shaders' else '') + '/objects/' + sha + '.tar.gz'
            remote.upload(dest, path)
            record['artifacts'].append(dict(kind=kind, cache_key=cache_key if kind == 'shaders' else None,
                                            path=path, sha256=sha, files=inv, context=context if kind == 'shaders' else None))
            print('Verified %s: %d files, %d bytes' % (kind, len(files), sum(v['size'] for v in inv.values())), flush=True)
        for artifact in record['artifacts']:
            if live and artifact['kind'] == 'shaders':
                continue
            if inventory(collect(m, root, artifact['kind'], scoped=live)) != artifact['files']:
                raise ValueError('State changed before publication; VM retained')
        commit = Path(tmp) / 'COMMITTED.json'
        commit.write_text(json.dumps(record, sort_keys=True))
        remote.upload(commit, 'state/' + gid + '/snapshots/' + snapshot + '/COMMITTED.json')
    return record


def unpack(artifact, archive_path, stage):
    if digest(archive_path) != artifact['sha256']:
        raise ValueError('State archive checksum failed')
    expected = artifact['files']; seen = set()
    with tarfile.open(archive_path, 'r:gz') as tar:
        for member in tar:
            name = member.name
            relative(name)
            if not member.isfile() or name not in expected or name in seen or member.size != expected[name]['size']:
                raise ValueError('Unsafe or unexpected state archive member: ' + name)
            if name.split('/')[0] not in ('prefix', 'game', 'saves', 'configs', 'shaders') or name.lower().endswith(('/nvngx.dll', '/_nvngx.dll')):
                raise ValueError('Invalid archive state base')
            dest = Path(stage) / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with tar.extractfile(member) as stream, dest.open('wb') as out:
                shutil.copyfileobj(stream, out)
            if digest(dest) != expected[name]['sha256']:
                raise ValueError('State file checksum failed')
            seen.add(name)
    if seen != set(expected):
        raise ValueError('Missing state archive files')


def restore(m, root, remote, cache_key, context=None, defer_shaders=False):
    record = latest(remote, m['id'])
    if not record:
        print('No previous game state; fresh session', flush=True)
        return None
    if record.get('game_version') != m.get('version', 'v1'):
        raise ValueError('State game version differs; migrate explicitly before launch')
    bases = roots(root, m['id'])
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / 'stage'; stage.mkdir()
        kinds = set()
        deferred = None
        for artifact in record['artifacts']:
            kind = artifact['kind']
            if kind not in ('saves', 'configs', 'shaders') or kind in kinds:
                raise ValueError('Invalid snapshot artifact kinds')
            kinds.add(kind)
            sha = artifact['sha256']
            if not re.fullmatch('[a-f0-9]{64}', sha):
                raise ValueError('Invalid archive checksum')
            key = artifact.get('cache_key')
            defer = False
            if kind == 'shaders' and context is not None and not context.get('gpu_driver'):
                print('GPU identity unavailable; shader cache reuse skipped', flush=True)
                continue
            if kind == 'shaders' and key != cache_key:
                prior_context = artifact.get('context')
                if defer_shaders and context and prior_context and {k:v for k,v in context.items() if k != 'builds'} == {k:v for k,v in prior_context.items() if k != 'builds'}:
                    defer = True
                else:
                    print('Shader compatibility differs; starting a new cache', flush=True)
                    continue
            expected_path = 'state/' + m['id'] + ('/shaders/' + key if kind == 'shaders' else '') + '/objects/' + sha + '.tar.gz'
            if artifact['path'] != expected_path:
                raise ValueError('State object outside game namespace')
            local = Path(tmp) / (kind + '.tar.gz')
            remote.download(artifact['path'], local)
            if defer:
                pending = Path(tmp) / 'pending'; pending.mkdir(exist_ok=True)
                unpack(artifact, local, pending)
                deferred = (artifact, pending)
            else:
                unpack(artifact, local, stage)
        if kinds != {'saves', 'configs', 'shaders'}:
            raise ValueError('Incomplete committed snapshot')
        # Validate every destination before changing any live file.
        copies = []
        for p in stage.rglob('*'):
            if not p.is_file(): continue
            base, rel = p.relative_to(stage).as_posix().split('/', 1)
            dest = bases[base] / rel
            if not dest.resolve().is_relative_to(bases[base].resolve()):
                raise ValueError('Restore destination symlink escapes game root')
            copies.append((p, dest, base))
        for p, dest, base in copies:
            dest.parent.mkdir(parents=True, exist_ok=True)
            bases[base].mkdir(parents=True, exist_ok=True)
            owner = dest.stat() if dest.exists() else bases[base].stat()
            temp = dest.with_name(dest.name + '.vastgame-tmp')
            shutil.copyfile(p, temp); temp.chmod(0o600)
            if os.geteuid() == 0:
                os.chown(temp, owner.st_uid, owner.st_gid)
                parent = dest.parent
                while parent != bases[base]:
                    os.chown(parent, owner.st_uid, owner.st_gid)
                    parent = parent.parent
            temp.replace(dest)
        if deferred:
            artifact, pending = deferred
            target = Path(root) / 'profiles' / m['id'] / 'pending-shaders'
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(pending, target)
            (target / 'artifact.json').write_text(json.dumps(artifact))
            if os.geteuid() == 0:
                owner = target.parent.stat()
                for item in [target, *target.rglob('*')]:
                    os.chown(item, owner.st_uid, owner.st_gid)
            print('Verified shader cache staged; runner compatibility checked immediately before Wine launches', flush=True)
    print('Restored verified snapshot ' + record['snapshot'], flush=True)
    return record


def containers(gid):
    ids = subprocess.check_output(['docker', 'ps', '-q'], text=True).split()
    if not ids: return []
    records = json.loads(subprocess.check_output(['docker', 'inspect', *ids], text=True))
    return [r['Id'] for r in records if any(v['Source'] == '/srv/gaming/prefixes' and v['Destination'] == '/prefixes' for v in r.get('Mounts', [])) and r.get('Name', '').startswith('/WolfLutris_vastgame_' + gid + '_')]


def idle(gid):
    # Require all processes using this exact Wine prefix to exit, not just the EXE.
    for container in containers(gid):
        container_state(container, 'idle', gid)


def container_state(container, action, gid):
    # Run the matching state helper through stdin; never replace a live container's code.
    subprocess.run(['docker', 'exec', '-i', container, 'python3', '-', action, gid],
                   input=Path(__file__).read_bytes(), check=True, timeout=15)


def container_idle(gid):
    prefix = '/prefixes/' + gid
    for p in Path('/proc').glob('[0-9]*'):
        try:
            env = (p / 'environ').read_bytes().split(b'\0')
            args = (p / 'cmdline').read_bytes()
            system = (b'explorer.exe', b'services.exe', b'winedevice.exe', b'wineboot.exe', b'rpcss.exe', b'conhost.exe', b'plugplay.exe')
            prefixes = [e[11:].decode() for e in env if e.startswith(b'WINEPREFIX=')]
            ours = any(Path(e).resolve() == Path(prefix).resolve() for e in prefixes)
            if ours and b'.exe' in args.lower() and not any(x in args.lower() for x in system):
                raise RuntimeError('Game/Wine still running. Exit the game cleanly, then retry; no backup or destroy was performed.')
        except (FileNotFoundError, ProcessLookupError):
            continue


def close_windows(gid):
    # WM_DELETE_WINDOW asks the game to quit through its normal UI; never SIGKILL.
    import ctypes as c
    from game_session import config
    m = json.loads((Path('/profiles') / gid / 'manifest.json').read_text())
    exe = Path(config(m)['game']['exe']).name.lower()
    display = None
    pids = set()
    for p in Path('/proc').glob('[0-9]*'):
        try:
            args = (p / 'cmdline').read_bytes().replace(b'\\', b'/').lower()
            if exe.encode() in args:
                pids.add(int(p.name))
                for entry in (p / 'environ').read_bytes().split(b'\0'):
                    if entry.startswith(b'DISPLAY='):
                        display = entry[8:]
        except OSError:
            continue
    if not display:
        return
    x = c.CDLL('libX11.so.6')
    pointer = c.c_void_p; ulong = c.c_ulong
    for name, restype, types in [
        ('XOpenDisplay', pointer, [c.c_char_p]),
        ('XDefaultRootWindow', ulong, [pointer]),
        ('XInternAtom', ulong, [pointer, c.c_char_p, c.c_int]),
        ('XQueryTree', c.c_int, [pointer, ulong, c.POINTER(ulong), c.POINTER(ulong), c.POINTER(c.POINTER(ulong)), c.POINTER(c.c_uint)]),
        ('XGetClassHint', c.c_int, [pointer, ulong, pointer]),
        ('XSendEvent', c.c_int, [pointer, ulong, c.c_int, c.c_long, pointer]),
        ('XGetWindowProperty', c.c_int, [pointer, ulong, ulong, c.c_long, c.c_long, c.c_int, ulong, c.POINTER(ulong), c.POINTER(c.c_int), c.POINTER(ulong), c.POINTER(ulong), c.POINTER(pointer)]),
        ('XFlush', c.c_int, [pointer]), ('XFree', c.c_int, [pointer]),
        ('XCloseDisplay', c.c_int, [pointer])]:
        getattr(x, name).restype = restype; getattr(x, name).argtypes = types
    class Hint(c.Structure):
        _fields_ = [('name', pointer), ('klass', pointer)]
    class Message(c.Structure):
        _fields_ = [('type', c.c_int), ('serial', ulong), ('send_event', c.c_int),
                    ('display', pointer), ('window', ulong), ('message_type', ulong),
                    ('format', c.c_int), ('data', c.c_long * 5)]
    class Event(c.Union):
        _fields_ = [('message', Message), ('pad', c.c_long * 24)]
    d = x.XOpenDisplay(display)
    if not d: return
    protocols = x.XInternAtom(d, b'WM_PROTOCOLS', 0)
    delete = x.XInternAtom(d, b'WM_DELETE_WINDOW', 0)
    pid_atom = x.XInternAtom(d, b'_NET_WM_PID', 0)
    def visit(window, depth=0):
        actual = ulong(); format_ = c.c_int(); nitems = ulong(); after = ulong(); data = pointer()
        owner = None
        if x.XGetWindowProperty(d, window, pid_atom, 0, 1, 0, 0, c.byref(actual), c.byref(format_), c.byref(nitems), c.byref(after), c.byref(data)) == 0 and data:
            if format_.value == 32 and nitems.value:
                owner = c.cast(data, c.POINTER(ulong))[0]
            x.XFree(data)
        hint = Hint(); names = []
        if x.XGetClassHint(d, window, c.byref(hint)):
            names = [c.string_at(v).decode(errors='replace').lower() for v in (hint.name, hint.klass) if v]
            for v in (hint.name, hint.klass):
                if v: x.XFree(v)
        if owner in pids or exe in names:
            event = Event()
            event.message.type = 33; event.message.send_event = 1
            event.message.display = d; event.message.window = window
            event.message.message_type = protocols; event.message.format = 32
            event.message.data[0] = delete
            x.XSendEvent(d, window, 0, 0, c.byref(event))
        if depth >= 6: return
        root = ulong(); parent = ulong(); children = c.POINTER(ulong)(); count = c.c_uint()
        if x.XQueryTree(d, window, c.byref(root), c.byref(parent), c.byref(children), c.byref(count)):
            for i in range(count.value): visit(children[i], depth + 1)
            if children: x.XFree(children)
    try:
        visit(x.XDefaultRootWindow(d)); x.XFlush(d)
    finally:
        x.XCloseDisplay(d)


def stop_cleanly(gid):
    for container in containers(gid):
        container_state(container, 'close', gid)
    deadline = time.monotonic() + 120
    while True:
        try:
            idle(gid)
            time.sleep(3)
            idle(gid)
            return
        except subprocess.CalledProcessError:
            if time.monotonic() >= deadline:
                raise RuntimeError('Game did not close cleanly within 120s; VM retained. Exit the game and retry.')
            time.sleep(2)


def prepare_shaders(gid):
    profile = Path('/profiles') / gid
    pending = profile / 'pending-shaders'
    if not pending.exists(): return
    artifact = json.loads((pending / 'artifact.json').read_text())
    context = json.loads((profile / 'cache-context.json').read_text())
    context['builds'] = runner_builds(gid, container=True)
    if context_key(context) != artifact['cache_key']:
        print('Installed runner build differs; shader cache skipped', flush=True)
        shutil.rmtree(pending)
        return
    bases = {base: Path('/' + folder) / gid for base, folder in
             [('game','games'), ('prefix','prefixes'), ('saves','saves'), ('configs','configs'), ('shaders','shaders')]}
    copies = []
    for name, expected in artifact['files'].items():
        relative(name)
        base, rel = name.split('/', 1)
        if base not in bases: raise ValueError('Invalid shader state base')
        src = pending / name; dest = bases[base] / rel
        if src.is_symlink() or not src.resolve().is_relative_to(pending.resolve()) or digest(src) != expected['sha256']:
            raise ValueError('Staged shader cache checksum/path failed')
        if not dest.resolve().is_relative_to(bases[base].resolve()):
            raise ValueError('Shader destination escapes game root')
        copies.append((src, dest))
    for src, dest in copies:
        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_name(dest.name + '.vastgame-tmp')
        shutil.copyfile(src, temp); temp.chmod(0o600); temp.replace(dest)
    shutil.rmtree(pending)
    print('Matching compiled shader cache restored before Wine launch', flush=True)


def wait_for_state_lock(lock, timeout=30, mode=fcntl.LOCK_EX, stopping=None, report=None):
    deadline = time.monotonic() + timeout
    reported = False
    while True:
        if stopping is not None and stopping.exists():
            raise RuntimeError('Final backup in progress; game launch blocked')
        try:
            fcntl.flock(lock, mode | fcntl.LOCK_NB)
            if stopping is not None and stopping.exists():
                fcntl.flock(lock, fcntl.LOCK_UN)
                raise RuntimeError('Shutdown pending; game launch blocked')
            return
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f'State lock still busy after {timeout:g}s: another game launch, '
                                   'backup or restore is active. VM retained; wait for it to finish and retry.') from None
            if not reported:
                if report:
                    report('Waiting for save/config backup or restore to finish')
                else:
                    print('Waiting for active game launch or state operation to release the state lock...', flush=True)
                reported = True
            time.sleep(min(0.2, remaining))


def main():
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'launch':
        gid = sys.argv[2]; gid_check(gid)
        with (Path('/profiles') / gid / 'state.lock').open('a') as lock:
            wait_for_state_lock(lock, timeout=300, mode=fcntl.LOCK_SH,
                                stopping=Path('/vastgame-status/stopping'))
            from prepare_game import prepared_environment
            os.environ.update(prepared_environment(gid))
            prepare_shaders(gid)
            os.execvpe(sys.argv[3], sys.argv[3:], os.environ)
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['backup', 'restore', 'idle', 'close', 'resume'])
    parser.add_argument('game_id')
    parser.add_argument('--root', default='/srv/gaming')
    parser.add_argument('--remote', default='gdrive:VastGaming')
    parser.add_argument('--config')
    parser.add_argument('--instance', default='')
    parser.add_argument('--label', default='')
    parser.add_argument('--receipt')
    parser.add_argument('--cache-key')
    parser.add_argument('--manifest-sha')
    parser.add_argument('--final', action='store_true')
    parser.add_argument('--live', action='store_true')
    a = parser.parse_args(); gid_check(a.game_id)
    if (a.final or a.live) and a.action != 'backup':
        raise ValueError('--final and --live apply only to backup')
    if a.final and a.live:
        raise ValueError('A live checkpoint cannot be a final backup')
    if a.action == 'close':
        close_windows(a.game_id); return
    if a.action == 'idle':
        container_idle(a.game_id); return
    if a.label and os.environ.get('VASTGAME_LAUNCH_LABEL', '') != a.label:
        saved = Path('/var/lib/vast-gaming/status/instance-label')
        if not saved.exists() or saved.read_text().strip() != a.label:
            raise ValueError('Connected VM does not match the selected Vast launch label')
    lockpath = Path(a.root) / 'profiles' / a.game_id / 'state.lock'
    with lockpath.open('a') as lock:
        if os.geteuid() == 0:
            owner = lockpath.parent.stat()
            os.fchown(lock.fileno(), owner.st_uid, owner.st_gid)
        if a.live:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print('Checkpoint deferred: launch/state operation active', flush=True)
                return
        else:
            wait_for_state_lock(lock)
        marker = Path('/var/lib/vast-gaming/status/stopping')
        raw = (Path(a.root) / 'profiles' / a.game_id / 'manifest.json').read_bytes()
        if a.manifest_sha and hashlib.sha256(raw).hexdigest() != a.manifest_sha:
            raise ValueError('VM save policy changed during state request; retry without replacing its manifest')
        m = json.loads(raw)
        if m['id'] != a.game_id:
            raise ValueError('Game ID differs from manifest')
        if a.action == 'resume':
            marker.unlink(missing_ok=True)
            print('Game launching re-enabled. No backup or destruction performed.', flush=True)
            return
        if marker.exists() and not a.final:
            if a.live:
                print('Checkpoint deferred: final shutdown pending', flush=True)
                return
            raise RuntimeError('Final shutdown block retained. Retry vastgame stop, or explicitly run vastgame state resume '+a.game_id)
        ordinary_backup = a.action == 'backup' and not a.live and not a.final
        try:
            if a.action == 'backup' and not a.live:
                marker.touch()
                stop_cleanly(a.game_id)
            elif a.action == 'restore':
                idle(a.game_id)
            context = cache_context(m) if not a.cache_key else None
            key = a.cache_key or context_key(context)
            if context:
                (Path(a.root) / 'profiles' / a.game_id / 'cache-context.json').write_text(json.dumps(context))
            remote = Remote(a.remote, a.config)
            result = backup(m, a.root, remote, a.instance, key, context, live=a.live) if a.action == 'backup' else restore(m, a.root, remote, key, context, defer_shaders=True)
            if not a.live:
                idle(a.game_id)
            if a.receipt and result:
                Path(a.receipt).write_text(json.dumps(result))
        finally:
            if ordinary_backup:
                marker.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        raise SystemExit('Game state failed: ' + str(exc))
