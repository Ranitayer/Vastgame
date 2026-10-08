"""Preview or remove only recognized, inactive local Vastgame artifacts."""
import argparse
from contextlib import ExitStack
import fcntl
import os
from pathlib import Path
import shutil
import time

DAY = 86400


def directories(root, pattern):
    if root.absolute() != root.resolve() or not root.is_dir():
        return []
    return [p for p in root.glob(pattern) if p.is_dir() and not p.is_symlink()]


def newest(paths):
    return sorted(paths, key=lambda p: (modified(p), p.name), reverse=True)


def modified(path):
    timestamp = path.stat().st_mtime
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(root)/name).is_symlink()]
        for name in dirs+files:
            timestamp = max(timestamp, (Path(root)/name).lstat().st_mtime)
    return timestamp


def candidates(app, state, data, now=None):
    now = time.time() if now is None else now
    protected = set()
    latest = state/'latest-report'
    if latest.is_file():
        protected.add(Path(latest.read_text().strip()).absolute())
    instance = state/'instance_id'
    if instance.is_file() and instance.read_text().strip().isdigit():
        protected.add(state/'reports'/instance.read_text().strip())
    moonlight = state/'moonlight.log'
    if moonlight.is_symlink():
        protected.add(moonlight.resolve().parent)
    rows = []
    for root, pattern, kind in [(state, 'hud.*', 'HUD session'),
                                (state/'reports', '[0-9]*', 'failure report'),
                                (state/'crashes', 'session-*', 'crash session')]:
        for path in newest(directories(root, pattern))[10:]:
            if path.absolute() not in protected and now-modified(path) >= 7*DAY:
                rows.append((path, kind))
    backups = newest(directories(data, 'app-backup.*'))
    valid = [p for p in backups if (p/'bin/vastgame').is_file() and (p/'src/manager/commands.sh').is_file()]
    # Unknown backups may contain recovery data. Delete only recognized older backends.
    for path in valid[1:]:
        if now-modified(path) >= DAY:
            rows.append((path, 'old Windows backend'))
    for root, pattern, kind in [(app/'build/core-vm-work', 'vastgame-core.*', 'Core build workspace'),
                                (state/'windows-build', 'private-*', 'Windows build workspace'),
                                (data, 'app-update.*', 'abandoned Windows update'),
                                (state, 'state.*', 'state transfer workspace')]:
        for path in directories(root, pattern):
            if now-modified(path) >= DAY:
                rows.append((path, kind))
    return rows


def activity():
    references = []
    for process in Path('/proc').iterdir():
        if not process.name.isdecimal() or int(process.name) == os.getpid():
            continue
        try:
            if process.stat().st_uid != os.getuid():
                continue
            paths = []
            for link in [process/'cwd', process/'exe', *list((process/'fd').iterdir())]:
                try:
                    paths.append(os.readlink(link).removesuffix(' (deleted)'))
                except FileNotFoundError:
                    pass
            references.extend((process.name, p) for p in paths)
            for file in ('cmdline', 'environ'):
                references.extend((process.name, value.decode(errors='replace'))
                                  for value in (process/file).read_bytes().split(b'\0'))
            references.extend((process.name, line) for line in (process/'maps').read_text().splitlines())
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            # Restricted processes must not crash the preview or weaken deletion checks.
            references.append((process.name, None))
    return references


def active(path, references):
    value = str(path.absolute())
    for pid, reference in references:
        if reference is not None and value in reference:
            return 'used by process '+pid
    for pid, reference in references:
        if reference is None:
            return 'process '+pid+' is unreadable; activity cannot be ruled out'
    pidfile = path/'pid'
    if pidfile.is_file():
        try:
            pid = int(pidfile.read_text())
            if pid > 0:
                os.kill(pid, 0)
                return 'session PID is still alive'
        except ProcessLookupError:
            pass
        except (PermissionError, ValueError):
            return 'session activity could not be verified'
    return ''


def allocated(path):
    total = 0
    device = path.stat().st_dev
    for root, dirs, files in os.walk(path, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(root)/name).is_symlink()]
        for name in dirs+files:
            item = (Path(root)/name).lstat()
            if item.st_dev != device:
                raise RuntimeError('Nested mounted filesystem; cleanup refused: '+str(path))
            total += item.st_blocks*512
    return total


def cleanup(app, state, data, apply=False):
    with ExitStack() as stack:
        if apply:
            # Match catalog writers' order, then exclude cooperating build processes.
            for path in (state/'lifecycle.lock', state/'catalog.lock', state/'build.lock', app/'build/.cleanup.lock'):
                path.parent.mkdir(parents=True, exist_ok=True)
                lock = stack.enter_context(path.open('a'))
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise RuntimeError('A Vastgame operation/build is active; nothing removed') from None
        rows = candidates(app, state, data)
        # With no eligible artifacts, process inspection cannot change the result.
        references = activity() if rows else []
        total = 0
        count = 0
        for path, kind in rows:
            reason = active(path, references)
            if reason:
                print('KEEP '+str(path)+' — '+reason)
                continue
            stat = path.lstat()
            size = allocated(path)
            if apply:
                # Recheck immediately before removal; never follow a replacement symlink.
                current = path.lstat()
                if path.absolute() != path.resolve() or (current.st_dev, current.st_ino, current.st_mtime_ns) != (stat.st_dev, stat.st_ino, stat.st_mtime_ns) or active(path, activity()):
                    print('KEEP '+str(path)+' — changed or active')
                    continue
                if not shutil.rmtree.avoids_symlink_attacks:
                    raise RuntimeError('Platform lacks safe directory removal; cleanup refused')
                shutil.rmtree(path)
            print(('REMOVED ' if apply else 'WOULD REMOVE ')+str(path)+f' — {kind}, {size/1024**2:.1f} MiB')
            total += size
            count += 1
        print(f'{"Removed" if apply else "Preview"}: {count} folders, {total/1024**2:.1f} MiB allocated.')
        print('Keeps 10 recent sessions/reports, 7 days of logs, and one valid Windows recovery backend.')
        print('Saves, credentials, host history, releases, ingest staging and remote data are outside cleanup scope.')
        if not apply:
            print('To remove the listed inactive artifacts: vastgame cleanup --apply')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    args = parser.parse_args()
    try:
        cleanup(args.app.absolute(), args.state.absolute(), args.data.absolute(), args.apply)
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, 'Cleanup stopped: '+str(exc)+'\n')


if __name__ == '__main__':
    main()
