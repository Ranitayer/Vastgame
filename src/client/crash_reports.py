#!/usr/bin/env python3
"""Private local session context and bounded log attachments for Crashpad."""
import argparse
import json
import os
from pathlib import Path
import shutil
import tempfile
import time


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def prepare(root, game_id, session_id):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    # Retain ten inactive sessions; never delete reports for a running client.
    previous = sorted((p for p in root.glob('session-*') if p.is_dir() and not p.is_symlink()),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    inactive = 0
    for path in previous:
        try:
            running = alive(int((path / 'pid').read_text()))
        except (OSError, ValueError):
            running = False
        if running:
            continue
        inactive += 1
        if inactive >= 10:
            shutil.rmtree(path)
    directory = Path(tempfile.mkdtemp(prefix='session-', dir=root))
    (directory / 'session.json').write_text(json.dumps(dict(game_id=game_id, session_id=session_id)))
    (directory / 'game_id.txt').write_text(game_id)
    (directory / 'session_id.txt').write_text(session_id)
    (directory / 'moonlight.log').touch()
    return directory.resolve()


def log_tail(source, destination):
    with source.open('rb') as stream:
        stream.seek(0, 2)
        stream.seek(max(0, stream.tell() - 128 * 1024))
        data = stream.read(128 * 1024)
    temporary = destination.with_suffix('.tmp')
    temporary.write_bytes(data)
    temporary.replace(destination)


def watch(directory, source, pid):
    (directory / 'pid').write_text(str(pid))
    started = time.monotonic()
    while True:
        try:
            log_tail(source, directory / 'moonlight.log')
        except OSError:
            pass
        if not alive(pid) or time.monotonic() - started > 48 * 3600:
            break
        time.sleep(2)
    # Give the handler time to finish publishing a dump after the process exits.
    time.sleep(2)
    if any(directory.glob('pending/*.dmp')) or any(directory.glob('completed/*.dmp')):
        print('Vastgame: native client crash report saved in ' + str(directory), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('prepare')
    create.add_argument('--root', type=Path, required=True)
    create.add_argument('--game', default='')
    create.add_argument('--session', default='')
    monitor = commands.add_parser('watch')
    monitor.add_argument('--directory', type=Path, required=True)
    monitor.add_argument('--log', type=Path, required=True)
    monitor.add_argument('--pid', type=int, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == 'prepare':
        print(prepare(args.root, args.game, args.session))
    else:
        watch(args.directory, args.log, args.pid)


if __name__ == '__main__':
    main()
