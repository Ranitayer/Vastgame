#!/usr/bin/env python3
"""Stream immutable game objects; publish verified metadata and the manifest last."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from game_catalog import atomic, check
from import_progress import Progress

CHUNK_BYTES = 256 * 1024 * 1024


def hash_file(path, algorithm='sha256', progress=None):
    digest = hashlib.new(algorithm)
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
            if progress: progress.advance(len(block))
    return digest.hexdigest()


def inventory(root):
    entries = []
    for path in sorted(root.rglob('*')):
        info = path.lstat()
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode)):
            raise ValueError('Unsupported special file in game source')
        if path.is_symlink() and not path.resolve().is_relative_to(root):
            raise ValueError('Source symlink escapes game folder')
        entries.append((path.relative_to(root).as_posix(), info.st_size, info.st_mtime_ns,
                        info.st_mode, path.readlink().as_posix() if path.is_symlink() else ''))
    return entries


def compressed_parts(root, work, digest, chunk_bytes=CHUNK_BYTES):
    # Pipes apply backpressure: no complete archive or unbounded parts directory.
    tar = subprocess.Popen(['tar', '--sort=name', '--mtime=@0', '--owner=0', '--group=0',
                            '--numeric-owner', '--format=gnu', '-C', str(root), '-cf', '-', '.'],
                           stdout=subprocess.PIPE)
    try:
        compressor = subprocess.Popen(['zstd', '-q', '-T2', '-c'], stdin=tar.stdout, stdout=subprocess.PIPE)
    except BaseException:
        tar.stdout.close(); tar.terminate(); tar.wait()
        raise
    tar.stdout.close()
    try:
        index = 0
        while True:
            path = work/f'part-{index:05d}'
            sha = hashlib.sha256(); md5 = hashlib.md5(); size = 0
            with path.open('wb') as output:
                while size < chunk_bytes:
                    block = compressor.stdout.read(min(1024*1024, chunk_bytes-size))
                    if not block: break
                    output.write(block); digest.update(block); sha.update(block); md5.update(block)
                    size += len(block)
            if not size:
                path.unlink(); break
            yield path, dict(name=path.name, size=size, sha256=sha.hexdigest()), md5.hexdigest()
            index += 1
        compressed_code = compressor.wait(); tar_code = tar.wait()
        if compressed_code or tar_code:
            raise ValueError('Game archive stream failed; manifest unchanged')
    finally:
        for process in (compressor, tar):
            if process.poll() is None: process.terminate()
        for process in (compressor, tar):
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()
        compressor.stdout.close()


def archive_format():
    return [subprocess.check_output([tool, '--version'], text=True).splitlines()[0]
            for tool in ('tar', 'zstd')]


def measure_package(source, work, progress):
    digest = hashlib.sha256(); size = 0
    with tempfile.TemporaryDirectory(prefix='measure-', dir=work) as tmp:
        iterator = compressed_parts(source, Path(tmp), digest)
        try:
            for path, part, _ in iterator:
                size += part['size']
                progress.advance(part['size'])
                path.unlink()
        finally:
            iterator.close()
    return dict(size=size, sha256=digest.hexdigest())


def remote_md5(remote):
    try:
        result = subprocess.check_output(['rclone', 'hashsum', 'MD5', remote], text=True,
                                         stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        raise ValueError('Remote object verification failed: '+exc.stderr.strip()) from exc
    rows = [line.split(None, 1) for line in result.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2:
        raise ValueError('Remote object verification failed: missing MD5')
    return rows[0][0].lower()


def prepare_upload_folder(remote, game_id):
    game = remote+f'/games/{game_id}'
    try:
        subprocess.run(['rclone', 'mkdir', game+'/objects'],
                       check=True, capture_output=True, text=True)
        for parent, name in ((remote+'/games', game_id), (game, 'objects')):
            entries = json.loads(subprocess.check_output(
                ['rclone', 'lsjson', parent, '--dirs-only'], text=True, stderr=subprocess.PIPE))
            matches = [entry for entry in entries if entry['Name'] == name]
            if len(matches) != 1:
                raise ValueError(f'Upload folder is ambiguous on Drive: {parent}/{name}. '
                                 'Merge duplicate folders before retrying; staging retained')
    except subprocess.CalledProcessError as exc:
        raise ValueError('Cannot prepare upload folder: '+exc.stderr.strip()) from exc


def copy_part(args, progress=None, name=None):
    if progress is None:
        subprocess.run(args, check=True)
        return
    process = subprocess.Popen(args+['--use-json-log', '--stats', '100ms', '--stats-log-level', 'NOTICE'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    errors = deque(maxlen=8)
    try:
        for line in process.stderr:
            try: record = json.loads(line)
            except ValueError:
                errors.append(line.strip()); continue
            stats = record.get('stats', {})
            if type(stats.get('bytes')) in (int, float): progress.upload(name, stats['bytes'])
            if record.get('level') in ('error', 'critical'): errors.append(record.get('msg', 'Upload failed'))
        if process.wait():
            reason = '; '.join(errors) or f'rclone exited {process.returncode}'
            raise ValueError('Chunk upload failed: '+reason)
    finally:
        process.stderr.close()
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait()


def upload_part(path, part, md5, remote, cached, progress=None):
    destination = remote+'/'+part['object']
    if not cached or cached.get('md5') != md5 or cached.get('sha256') != part['sha256']:
        copy_part(['rclone', 'copyto', str(path), destination, '--immutable', '--checksum',
                   '--no-update-modtime', '--drive-chunk-size', '64M', '--retries', '3'], progress, part['name'])
    if remote_md5(destination) != md5:
        raise ValueError('Remote package part verification failed; manifest unchanged')
    if progress: progress.verify(part['name'])
    return dict(part, md5=md5)


def publish_file(path, remote):
    subprocess.run(['rclone', 'copyto', str(path), remote, '--immutable', '--checksum',
                    '--no-update-modtime', '--retries', '3'], check=True)
    if subprocess.check_output(['rclone', 'cat', remote]) != path.read_bytes():
        raise ValueError('Remote package commit verification failed; manifest unchanged')


def publish(manifest, source, work, remote='gdrive:VastGaming', imported=False, progress=None):
    if progress is not None:
        return _publish(manifest, source, work, remote, imported, progress)
    with Progress() as display:
        result = _publish(manifest, source, work, remote, imported, display)
        display.phase('Package complete', 0, detail=result['id'])
        return result


def _publish(manifest, source, work, remote, imported, progress):
    manifest = Path(manifest); source = Path(source).resolve(strict=True); work = Path(work)
    if work.resolve().is_relative_to(source):
        raise ValueError('Upload workspace must be outside the game source')
    m = json.loads(manifest.read_text()); check(m, source)
    progress.phase('4/6 Scanning game files')
    before = inventory(source)
    unpacked = sum(size for name, size, _, mode, _ in before if stat.S_ISREG(mode))
    if not unpacked: raise ValueError('Empty game source')
    work.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(work).free < CHUNK_BYTES*2 + 64*1024**2:
        raise ValueError('Packaging requires 576 MiB free workspace for bounded chunks')
    identity = hashlib.sha256(json.dumps(before).encode()).hexdigest()
    journal_path = work/'publication.json'
    journal = json.loads(journal_path.read_text()) if journal_path.exists() else {}
    if journal.get('source') != identity or journal.get('remote') != remote or journal.get('game') != m['id']:
        journal = dict(source=identity, remote=remote, game=m['id'], verified={})
    # Separate Drive processes can otherwise create duplicate parent folders concurrently.
    progress.phase('4/6 Preparing upload folder')
    prepare_upload_folder(remote, m['id'])
    game_size = f'Game size {unpacked/1024**3:.2f} GiB'
    format_version = archive_format()
    measured = journal.get('measurement', {})
    if (not isinstance(measured, dict) or measured.get('format') != format_version
            or type(measured.get('size')) is not int or measured['size'] <= 0
            or not isinstance(measured.get('sha256'), str)
            or not re.fullmatch('[0-9a-f]{64}', measured['sha256'])):
        progress.phase('4/6 Measuring full upload size', detail=game_size)
        measured = measure_package(source, work, progress)
        if not measured['size'] or inventory(source) != before:
            raise ValueError('Game source changed while measuring; manifest unchanged')
        measured['format'] = format_version
        journal['measurement'] = measured
        atomic(journal_path, journal)
    digest = hashlib.sha256(); parts = []; pending = deque()
    progress.begin_upload(measured['size'], detail=game_size)

    def finish():
        future, path = pending.popleft()
        receipt = future.result()
        journal['verified'][receipt['name']] = receipt
        atomic(journal_path, journal)
        path.unlink()


    with tempfile.TemporaryDirectory(prefix='chunks-', dir=work) as tmp:
        iterator = compressed_parts(source, Path(tmp), digest)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                while True:
                    if len(pending) == 2: finish()
                    try: path, part, md5 = next(iterator)
                    except StopIteration: break
                    part['object'] = f'games/{m["id"]}/objects/{part["sha256"]}.part'
                    parts.append(part)
                    progress.part(part['name'], part['size'])
                    pending.append((pool.submit(upload_part, path, part, md5, remote,
                                                journal['verified'].get(part['name']), progress), path))
                while pending: finish()
        finally:
            iterator.close()
    progress.phase('5/6 Verifying source and publishing commits')
    if not parts or inventory(source) != before:
        raise ValueError('Game source changed while packaging; previous manifest retained')
    sha = digest.hexdigest(); base = f'games/{m["id"]}/{sha}'
    if sum(part['size'] for part in parts) != measured['size'] or sha != measured['sha256']:
        journal.pop('measurement', None)
        atomic(journal_path, journal)
        raise ValueError('Archive differs from its measured size or checksum; manifest unchanged. Retry to remeasure')
    m.setdefault('version', 'v1')
    m['package'] = dict(version=sha, archive=base+'/game.tar.zst', checksum=base+'/game.tar.zst.sha256',
                        sha256=sha, size=sum(p['size'] for p in parts), unpacked_bytes=unpacked, parts=parts)
    if imported: m.pop('source', None)
    check(m, source)
    with tempfile.TemporaryDirectory(prefix='commit-', dir=work) as tmp:
        directory = Path(tmp)
        checksum = directory/'game.tar.zst.sha256'; checksum.write_text(sha+'  game.tar.zst\n')
        committed = directory/'COMMITTED.json'; committed.write_text(json.dumps(m['package'], sort_keys=True))
        publish_file(checksum, remote+'/'+base+'/'+checksum.name)
        publish_file(committed, remote+'/'+base+'/'+committed.name)
        public = dict(m); public.pop('source', None)
        metadata = directory/'manifest.json'; atomic(metadata, public)
        metadata_sha = hash_file(metadata)
        publish_file(metadata, remote+f'/games/{m["id"]}/manifests/{metadata_sha}.json')
    atomic(manifest, m)
    journal_path.unlink(missing_ok=True)
    return m


if __name__ == '__main__':
    try:
        publish(*map(Path, sys.argv[1:4]))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise SystemExit('Package publication failed: '+str(exc))
