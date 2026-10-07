#!/usr/bin/env python3
"""Prepare the selected Lutris environment without starting the game's EXE."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
from game_session import register, validate


def check_writable_paths(manifest):
    gid = manifest['id']
    paths = [Path('/profiles') / gid / 'logs', Path('/prefixes') / gid,
             Path('/shaders') / gid / 'cache', Path('/var/lutris'), Path('/vastgame-status')]
    paths += [Path.home() / name for name in ('.local', '.config', '.cache')]
    for path in paths:
        try:
            path.mkdir(parents=True, exist_ok=True)
            # Check actual writes as the container user, not host-root access().
            with tempfile.TemporaryFile(dir=path):
                pass
        except OSError as error:
            raise RuntimeError(f'Preparation user {os.getuid()}:{os.getgid()} cannot write {path}; '
                               'check bind-mount ownership and permissions') from error


def manifest_key(manifest):
    launch = {key: manifest.get(key) for key in ('id', 'version', 'game', 'runner', 'environment', 'compatibility', 'graphics')}
    return hashlib.sha256(json.dumps(launch, sort_keys=True).encode()).hexdigest()


def progress(key, state, action, root=Path('/vastgame-status')):
    root.mkdir(parents=True, exist_ok=True)
    dest = root / (key + '.json')
    temp = dest.with_suffix('.' + str(os.getpid()) + '.tmp')
    temp.write_text(json.dumps(dict(state=state, action=action, updated=time.time())))
    temp.replace(dest)
    print('[VASTGAME] ' + action, flush=True)


def prefix_ready(prefix):
    root = Path(prefix)
    return all((root / name).is_file() and (root / name).stat().st_size > 0
               for name in ('user.reg', 'system.reg', 'userdef.reg', 'drive_c/windows/system32/cmd.exe'))


def require_ready(manifest):
    profile = Path('/profiles') / manifest['id']
    try:
        record = json.loads((profile / 'prepared.json').read_text())
    except (OSError, ValueError) as exc:
        raise RuntimeError('Game environment preparation did not complete; see logs/preparation.log') from exc
    if record.get('manifest_sha256') != manifest_key(manifest) or not prefix_ready('/prefixes/' + manifest['id']):
        raise RuntimeError('Game environment was not prepared for this manifest; see logs/preparation.log')


def prepared_environment(gid):
    record = json.loads((Path('/profiles') / gid / 'prepared.json').read_text())
    env = record.get('environment', {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
        raise RuntimeError('Invalid prepared runner environment')
    if env.get('PROTONPATH') and not (Path(env['PROTONPATH']) / 'proton').is_file():
        raise RuntimeError('Prepared Proton build is missing; see preparation.log')
    return env


def pin_environment(env, command):
    if not command[0].endswith(('/umu-run', '/umu_run.py')):
        return {}
    pinned = {'UMU_RUNTIME_UPDATE': '0'}
    proton = env.get('PROTONPATH', '')
    if Path(proton).is_absolute() and (Path(proton) / 'proton').is_file():
        pinned['PROTONPATH'] = proton
    elif proton == 'GE-Proton':
        home = Path(env['HOME'])
        locations = (home / '.local/share/Steam/compatibilitytools.d', home / '.local/share/umu/compatibilitytools')
        candidates = [p for root in locations if root.is_dir() for p in root.iterdir()
                      if p.name.startswith('GE-Proton') and (p / 'proton').is_file()]
        if len(candidates) == 1:
            pinned['PROTONPATH'] = str(candidates[0])
    return pinned


def runtime_seed_environment(manifest, profiles=Path('/profiles')):
    # Honor only the generic GE-Proton seed, never override a custom runner.
    if manifest.get('runner', {}).get('version', 'ge-proton').lower() != 'ge-proton':
        return {}
    seed = profiles / manifest['id'] / 'runtime-seed.json'
    if not seed.is_file():
        return {}
    env = json.loads(seed.read_text())
    if (not isinstance(env, dict) or set(env) != {'PROTONPATH', 'UMU_RUNTIME_UPDATE'}
            or not isinstance(env['PROTONPATH'], str) or env['UMU_RUNTIME_UPDATE'] != '0'
            or not Path(env['PROTONPATH']).is_absolute()
            or not (Path(env['PROTONPATH']) / 'proton').is_file()):
        raise RuntimeError('Prebuilt Proton cache is incomplete or invalid')
    return env


def prepare(manifest, runner):
    prefix = '/prefixes/' + manifest['id']
    Path('/shaders/' + manifest['id'] + '/cache').mkdir(parents=True, exist_ok=True)
    progress('proton', 'running', 'Preparing Proton and Steam Runtime')
    # Use the installed runner's command/environment, including UMU's GE-Proton
    # selection. cmd.exe initializes Wine and exits; never pass the game's EXE.
    runner.get_executable(fallback=False)
    env = dict(os.environ)
    env.update(runner.get_env(os_env=True))
    env.update(manifest.get('environment', {}))
    env['WINEPREFIX'] = prefix
    runner.finish_env(env, None)
    env.update(runtime_seed_environment(manifest))
    env['PROTON_VERB'] = 'waitforexitandrun'
    command = runner.get_command()
    if not command:
        raise RuntimeError('Lutris returned no command for the requested runner')
    progress('prefix', 'running', 'Creating game prefix')
    subprocess.run([*command, 'cmd.exe', '/c', 'exit', '0'], env=env, check=True, timeout=1800)
    if not prefix_ready(prefix):
        raise RuntimeError('Proton returned without a valid game prefix')
    progress('proton', 'done', 'Proton and Steam Runtime prepared')
    progress('prefix', 'done', 'Game prefix created')
    progress('dx12', 'running', 'Preparing DX12 (DXVK / VKD3D)')
    managers = runner.get_dll_managers(enabled_only=True)
    for manager in managers:
        if str(manager.version).lower() == 'manual':
            continue
        if not Path(manager.versions_path).is_file():
            Path(manager.base_dir).mkdir(parents=True, exist_ok=True)
            manager.fetch_versions()
        if not manager.is_available():
            if not manager.download() or not manager.is_available():
                raise RuntimeError('Failed to prepare ' + manager.human_name)
    runner.prelaunch()
    for manager in managers:
        if str(manager.version).lower() != 'manual' and not manager.is_available():
            raise RuntimeError('Graphics runtime unavailable: ' + manager.human_name)
    # Components may intentionally omit a DLL for one architecture. Validate
    # files the selected bundle actually supplies, rather than inventing requirements.
    for manager in managers:
        if str(manager.version).lower() == 'manual':
            continue
        provided = 0
        for system_dir, arch, dll in manager._iter_dlls():
            source = Path(manager.path) / arch / (dll + '.dll')
            if not source.is_file():
                continue
            file = Path(system_dir) / (dll + '.dll')
            if not file.is_file() or file.stat().st_size == 0:
                raise RuntimeError('Graphics DLL missing after setup: ' + str(file))
            provided += 1
        if not provided and manager.managed_dlls:
            raise RuntimeError('Graphics runtime contains no usable DLLs: ' + manager.human_name)
    progress('dx12', 'done', 'DXVK / VKD3D prepared')
    env.update(runner.get_env(os_env=True))
    env.update(manifest.get('environment', {}))
    runner.finish_env(env, None)
    env['WINEPREFIX'] = prefix
    env['PROTON_VERB'] = 'waitforexitandrun'
    subprocess.run([*command, 'cmd.exe', '/c', 'exit', '0'], env=env, check=True, timeout=120)
    profile = Path('/profiles') / manifest['id']
    record = dict(manifest_sha256=manifest_key(manifest), updated=time.time(), environment=pin_environment(env, command))
    tmp = profile / 'prepared.tmp'
    tmp.write_text(json.dumps(record)); tmp.replace(profile / 'prepared.json')
    progress('setup', 'running', 'Game environment prepared; restoring persistent state')


def install_runtime_components(names):
    # Reuse Lutris's trusted runtime catalogue and synchronous extraction logic.
    # Its normal downloader relies on GTK callbacks; setup has no GTK main loop.
    from lutris.runtime import RuntimeUpdater
    from lutris.util import http
    updater = RuntimeUpdater(force=True)
    # A partial directory can have a recent timestamp but no usable component.
    # Select from the catalogue before its timestamp-based update filter.
    components = {item.name: item for item in updater._get_runtime_updaters(updater.runtime_versions) if item.name in names}
    missing = names - components.keys()
    if missing:
        raise RuntimeError('Lutris runtime catalogue contains no installable component: ' + ', '.join(sorted(missing)))
    for component in components.values():
        if getattr(component, 'url', None):
            Path(component.archive_path).parent.mkdir(parents=True, exist_ok=True)
            http.download_file(component.url, component.archive_path)
            component._install(component.archive_path)
        else:
            component.install_update(updater)


def ensure_umu():
    from lutris.util.wine.proton import get_umu_path
    from lutris.exceptions import MissingExecutableError
    try:
        return get_umu_path()
    except MissingExecutableError:
        pass
    progress('proton', 'running', 'Preparing Proton: downloading UMU launcher')
    install_runtime_components({'umu'})
    return get_umu_path()


def main():
    manifest = validate(json.loads(Path(sys.argv[1]).read_text()))
    (Path('/profiles') / manifest['id'] / 'prepared.json').unlink(missing_ok=True)
    check_writable_paths(manifest)
    gid = register(manifest, preparing=True)
    if 'proton' in manifest.get('runner', {}).get('version', 'ge-proton').lower():
        ensure_umu()
    from lutris.game import Game
    game = Game(gid)
    if not game.runner:
        raise RuntimeError('Lutris did not load the selected Wine runner')
    missing = {manager.name for manager in game.runner.get_dll_managers(enabled_only=True)
               if str(manager.version).lower() != 'manual' and (not Path(manager.base_dir).is_dir() or not manager.version)}
    if missing:
        progress('dx12', 'running', 'Preparing DX12: downloading ' + ', '.join(sorted(missing)))
        install_runtime_components(missing)
    prepare(manifest, game.runner)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        traceback.print_exc()
        progress('error', 'error', 'Game environment preparation failed: ' + str(exc))
        sys.exit(1)
