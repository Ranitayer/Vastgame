"""Install/update the shared backend and Windows bridge under coordinated locks."""
import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

NATIVE = ('vastgame-desktop.exe', 'desktop-build.json', 'Ensure-Desktop.ps1', 'Native-Screen.ps1', 'Native-Ping.ps1', 'Edit-Stream-Settings.cmd', 'Vastgame.cmd',
          'Edit-Stream-Settings.ps1',
          'Check-Updates.ps1', 'Update-Vastgame.cmd', 'Update-Vastgame.ps1', 'Install-Vastgame.ps1',
          'Complete-Setup.ps1', 'Prepare-WSL.ps1', 'WINDOWS-README.txt', 'release.json')


def replace(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output: output.write(content)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def verify(bundle, installed=None):
    release = json.loads((bundle/'release.json').read_text())
    if release.get('schema') != 1 or not isinstance(release.get('files'), dict):
        raise ValueError('Invalid Vastgame release manifest')
    required = set(NATIVE)-{'release.json'} | {'backend.tar.gz', 'run-vastgame.sh', 'windows-bridge.sh',
        'stream.json', 'apply_update.py', 'update-backend.sh', 'install-backend.sh', 'prepare-network.sh', 'dependencies.json'}
    if not required <= release['files'].keys(): raise ValueError('Incomplete Vastgame release')
    for name, digest in release['files'].items():
        if Path(name).name != name or not isinstance(digest, str) or len(digest) != 64:
            raise ValueError('Unsafe release member')
        # Setup resumes from the installed folder, whose stream file belongs to the user.
        if name == 'stream.json' and installed and bundle.resolve() == installed.resolve(): continue
        if hashlib.sha256((bundle/name).read_bytes()).hexdigest() != digest:
            raise ValueError('Release checksum mismatch: '+name)
    return release


def apply(home, bundle, application, tailscale, powershell, fresh=False):
    release = verify(bundle, application if fresh else None)
    base = home/'.local/share/vastgame'; state = home/'.local/state/vastgame'
    if not fresh:
        for name in ('.config/vastai/vast_api_key', '.config/rclone/rclone.conf', '.config/vastgame/template_hash'):
            if not (home/name).is_file() or not (home/name).stat().st_size: raise ValueError('Complete Vastgame Setup first: account configuration is missing')
    for path in (application/'Moonlight/Moonlight.exe', tailscale, powershell):
        if not path.is_file(): raise ValueError('Installed Windows integration path missing: '+str(path))
    state.mkdir(parents=True, exist_ok=True); base.mkdir(parents=True, exist_ok=True)
    with ExitStack() as locks:
        for name in ('lifecycle.lock', 'catalog.lock'):
            lock = locks.enter_context((state/name).open('a'))
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: raise ValueError('Another Vastgame operation/import is active; retry when it finishes') from None
        with tempfile.TemporaryDirectory(prefix='app-update.', dir=base, delete=False) as tmp:
            stage = Path(tmp); next_app = stage/'app'; next_app.mkdir()
            with tarfile.open(bundle/'backend.tar.gz') as archive:
                members = archive.getmembers(); seen = set(); total = 0
                for member in members:
                    path = Path(member.name); total += member.size
                    if (not member.isfile() or path.is_absolute() or '..' in path.parts or
                        member.name in seen or not path.parts or path.parts[0] not in ('bin', 'src') or total > 64*1024**2):
                        raise ValueError('Unsafe backend archive')
                    seen.add(member.name)
                archive.extractall(next_app, filter='data')
            if not (next_app/'bin/vastgame').is_file(): raise ValueError('Backend entry point missing')
            for path in [next_app/'bin/vastgame', *next_app.rglob('*.sh')]:
                subprocess.run(['bash', '-n', str(path)], check=True, capture_output=True)
            for path in next_app.rglob('*.py'): compile(path.read_text(), str(path), 'exec')
            (next_app/'bin/vastgame').chmod(0o755)
            targets = {application/name: (bundle/name).read_bytes() for name in release['files'] if name != 'stream.json'}
            targets[application/'release.json'] = (bundle/'release.json').read_bytes()
            if not (application/'stream.json').exists(): targets[application/'stream.json'] = (bundle/'stream.json').read_bytes()
            targets[home/'.local/bin/vastgame'] = (bundle/'run-vastgame.sh').read_bytes()
            for name in ('tailscale', 'moonlight', 'vastgame-native', 'ping'):
                targets[home/'.local/bin'/name] = (bundle/'windows-bridge.sh').read_bytes()
            config = home/'.config/vastgame/windows.json'
            settings = json.loads(config.read_text()) if config.exists() else {}
            settings.update(application=str(application), tailscale=str(tailscale), powershell=str(powershell))
            targets[config] = json.dumps(settings).encode()
            original = {}
            for path in targets:
                if path.is_symlink() or (path.exists() and not path.is_file()): raise ValueError('Unsafe update destination: '+str(path))
                original[path] = (path.read_bytes(), path.stat().st_mode & 0o777) if path.exists() else None
            recovery = stage/'recovery'; recovery.mkdir()
            for i, previous in enumerate(original.values()):
                if previous: replace(recovery/str(i), previous[0], previous[1])
            replace(recovery/'paths.json', json.dumps([str(p) for p in original]).encode())
            app = base/'app'
            if app.is_symlink() or (app.exists() and not app.is_dir()): raise ValueError('Unsafe backend destination')
            backup = None; activated = False; changed = []
            try:
                for path, content in targets.items():
                    replace(path, content, 0o755 if path.parent == home/'.local/bin' else 0o600)
                    changed.append(path)
                if app.exists():
                    backup = Path(tempfile.mkdtemp(prefix='app-backup.', dir=base)); backup.rmdir()
                    os.replace(app, backup)
                os.replace(next_app, app); activated = True
                if backup:
                    os.replace(recovery, backup/'windows-recovery')
                print('Vastgame '+release['version']+' installed. Existing accounts, games, stream settings and VMs preserved.')
                if backup: print('Recovery backend: '+str(backup))
                shutil.rmtree(stage)
            except BaseException:
                errors = []
                try:
                    if activated: shutil.rmtree(app)
                    if backup and backup.exists(): os.replace(backup, app)
                except OSError as exc: errors.append(str(exc))
                for path in reversed(changed):
                    try:
                        previous = original[path]
                        if previous: replace(path, previous[0], previous[1])
                        else: path.unlink(missing_ok=True)
                    except OSError as exc: errors.append(str(exc))
                if errors: raise RuntimeError('Update failed; rollback needs repair. Recovery: '+str(backup)+', '+str(stage)+'; '+'; '.join(errors))
                shutil.rmtree(stage)
                raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('home', 'bundle', 'application', 'tailscale', 'powershell'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--fresh', action='store_true')
    args = parser.parse_args()
    try: apply(args.home, args.bundle, args.application, args.tailscale, args.powershell, args.fresh)
    except Exception as exc: parser.exit(1, 'Update failed: '+str(exc)+'\n')
