#!/usr/bin/env python3
"""Restore existing multipart packages without assembling a second full archive."""
from concurrent.futures import ThreadPoolExecutor
from collections import deque
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

from game_session import validate


def package_parts(manifest):
    validate(manifest)
    package = manifest['package']
    parts = package['parts']
    if not isinstance(parts, list) or not parts:
        raise ValueError('Missing package parts')
    for index, part in enumerate(parts):
        if part.get('name') != f'part-{index:05d}':
            raise ValueError('Package parts must be consecutive and ordered')
        if not re.fullmatch('[a-f0-9]{64}', part.get('sha256', '')):
            raise ValueError('Invalid part checksum')
        if type(part.get('size')) is not int or part['size'] <= 0:
            raise ValueError('Invalid part size')
    if type(package.get('size')) is not int or sum(p['size'] for p in parts) != package['size']:
        raise ValueError('Package sizes do not match')
    return parts


class Progress:
    def __init__(self, path, parts):
        self.path = path
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.started = time.monotonic()
        self.samples = deque([(self.started, 0)], maxlen=6)
        self.received = [0] * len(parts)
        self.data = dict(state='running', action='Downloading and extracting',
                         total=sum(p['size'] for p in parts), bytes=0,
                         verified_parts=0, total_parts=len(parts), streamed_bytes=0)
        self.thread = threading.Thread(target=self.heartbeat, daemon=True)

    def write(self):
        if not self.path:
            return
        with self.lock:
            data = dict(self.data)
            data['bytes'] = sum(self.received)
        now = time.monotonic()
        if now - self.samples[-1][0] >= 0.2:
            self.samples.append((now, data['bytes']))
        first_time, first_bytes = self.samples[0]
        data['speed'] = max(0, data['bytes'] - first_bytes) / max(0.001, now - first_time)
        data['eta'] = (data['total'] - data['bytes']) / data['speed'] if data['speed'] else None
        data['updated'] = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.game-')
        try:
            with os.fdopen(fd, 'w') as output:
                json.dump(data, output)
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def heartbeat(self):
        while not self.stop.wait(1):
            self.write()


class Downloads:
    def __init__(self, remote, cache, progress, config):
        self.remote, self.cache, self.progress, self.config = remote, cache, progress, config
        self.cancel = threading.Event()
        self.lock = threading.Lock()
        self.processes = set()

    def close(self):
        self.cancel.set()
        with self.lock:
            for process in self.processes:
                if process.poll() is None:
                    process.kill()

    def fetch(self, index, part):
        target = self.cache / part['name']
        # Each retry starts a fresh file/hash; failed stdout is never concatenated.
        for attempt in range(3):
            if self.cancel.is_set():
                raise RuntimeError('Restore cancelled')
            digest = hashlib.sha256()
            size = 0
            with self.progress.lock:
                self.progress.received[index] = 0
            with tempfile.TemporaryFile() as errors:
                command = ['rclone', 'cat', self.remote + '/' + part['name'],
                           '--retries', '1', '--low-level-retries', '3',
                           '--contimeout', '10s', '--timeout', '30s']
                if self.config:
                    command += ['--config', self.config]
                with self.lock:
                    if self.cancel.is_set():
                        raise RuntimeError('Restore cancelled')
                    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
                    self.processes.add(process)
                try:
                    with target.open('wb') as output:
                        while block := process.stdout.read(1024 * 1024):
                            size += len(block)
                            if size > part['size'] or self.cancel.is_set():
                                raise RuntimeError('Oversized part or cancelled restore')
                            digest.update(block)
                            output.write(block)
                            with self.progress.lock:
                                self.progress.received[index] = size
                    code = process.wait()
                    if code == 0 and size == part['size'] and digest.hexdigest() == part['sha256']:
                        with self.progress.lock:
                            self.progress.data['verified_parts'] += 1
                        return target
                    errors.seek(0)
                    detail = errors.read()[-2000:].decode(errors='replace')
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                    process.stdout.close()
                    with self.lock:
                        self.processes.discard(process)
            if attempt == 2:
                raise RuntimeError(f'{part["name"]}: download/checksum failed ({size}/{part["size"]} bytes). {detail}')


def restore(manifest, checksum, root, remote, config=None, status=None, workers=8):
    parts = package_parts(manifest)
    expected = checksum.split()[0] if checksum.split() else ''
    if not re.fullmatch('[a-f0-9]{64}', expected):
        raise ValueError('Invalid archive checksum')
    workers = min(max(1, workers), len(parts))
    root.mkdir(parents=True, exist_ok=True)
    target = root / manifest['id']
    stage = root / (manifest['id'] + '.installing')
    previous = root / (manifest['id'] + '.previous')
    progress = Progress(status, parts)
    with (root / ('.' + manifest['id'] + '.restore.lock')).open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Recover an interrupted publication before starting a new installation.
        if previous.exists() and not target.exists():
            previous.rename(target)
        if previous.exists():
            shutil.rmtree(previous)
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(mode=0o700)
        with tempfile.TemporaryDirectory(prefix='.parts-', dir=root) as temporary:
            downloads = Downloads(remote, Path(temporary), progress, config)
            pool = ThreadPoolExecutor(max_workers=workers)
            decoder = extractor = None
            progress.thread.start()
            progress.write()
            try:
                with tempfile.TemporaryFile() as errors:
                    decoder = subprocess.Popen(['zstd', '-dc'], stdin=subprocess.PIPE,
                                               stdout=subprocess.PIPE, stderr=errors)
                    extractor = subprocess.Popen(['tar', '--no-same-owner', '-xf', '-', '-C', str(stage)],
                                                 stdin=decoder.stdout, stderr=errors)
                    decoder.stdout.close()
                    pending = {i: pool.submit(downloads.fetch, i, parts[i]) for i in range(workers)}
                    digest = hashlib.sha256()
                    for index, part in enumerate(parts):
                        file = pending.pop(index).result()
                        with file.open('rb') as source:
                            while block := source.read(1024 * 1024):
                                digest.update(block)
                                decoder.stdin.write(block)
                                with progress.lock:
                                    progress.data['streamed_bytes'] += len(block)
                        file.unlink()
                        following = index + workers
                        if following < len(parts):
                            pending[following] = pool.submit(downloads.fetch, following, parts[following])
                    decoder.stdin.close()
                    with progress.lock:
                        progress.data['action'] = 'Finishing extraction and validating installation'
                    progress.write()
                    decode_code = decoder.wait(timeout=300)
                    extract_code = extractor.wait(timeout=300)
                    if decode_code or extract_code:
                        errors.seek(0)
                        raise RuntimeError('Extraction failed: ' + errors.read()[-3000:].decode(errors='replace'))
                    if digest.hexdigest() != expected:
                        raise RuntimeError('Whole archive checksum mismatch; installation not published')
                    exe = (stage / manifest['game']['executable']).resolve()
                    working = (stage / manifest['game'].get('working_dir', '')).resolve()
                    if not exe.is_relative_to(stage.resolve()) or not exe.is_file():
                        raise ValueError('Restored executable missing or outside game directory')
                    if not working.is_relative_to(stage.resolve()) or not working.is_dir():
                        raise ValueError('Restored working directory missing or outside game directory')
                    if target.exists():
                        target.rename(previous)
                    try:
                        stage.rename(target)
                    except BaseException:
                        if previous.exists():
                            previous.rename(target)
                        raise
                    if previous.exists():
                        shutil.rmtree(previous)
                    with progress.lock:
                        progress.data.update(state='done', action='Game package ready: ' + manifest['id'],
                                             restore_mbps=progress.data['total'] * 8 / max(.001, time.monotonic()-progress.started) / 1e6,
                                             source='drive', machine_id=os.environ.get('VASTGAME_MACHINE_ID', ''),
                                             launch_label=os.environ.get('VASTGAME_LAUNCH_LABEL', ''))
            except BaseException as error:
                with progress.lock:
                    progress.data.update(state='error', action=str(error))
                raise
            finally:
                downloads.close()
                for process in (decoder, extractor):
                    if process and process.poll() is None:
                        process.kill()
                    if process:
                        process.wait()
                if decoder and not decoder.stdin.closed:
                    try:
                        decoder.stdin.close()
                    except BrokenPipeError:
                        pass
                pool.shutdown(wait=True, cancel_futures=True)
                progress.stop.set()
                progress.thread.join()
                progress.write()


if __name__ == '__main__':
    def interrupted(signum, frame):
        raise RuntimeError('Restore interrupted')
    signal.signal(signal.SIGTERM, interrupted)
    try:
        m = json.loads(Path(sys.argv[1]).read_text())
        restore(m, Path(sys.argv[2]).read_text(), Path('/srv/gaming/games'),
                'gdrive:VastGaming/' + str(Path(m['package']['archive']).parent) + '/parts',
                config='/etc/rclone/rclone.conf', status=Path('/var/lib/vast-gaming/status/game.json'))
    except Exception as error:
        print('[VASTGAME] Multipart restore failed: ' + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
