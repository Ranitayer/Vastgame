#!/usr/bin/env python3
"""Import a direct portable-game ZIP through the shared catalog and publisher."""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from game_catalog import atomic, create, valid_id
from package_publish import hash_file, publish
from import_progress import Progress

BLOCK = 1024 * 1024
RESERVE = 576 * 1024 * 1024
RANGE_BYTES = 32 * 1024 * 1024
ZIP_METHODS = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA}
# Python 3.14 reads both current and legacy Zstandard ZIP method IDs.
if hasattr(zipfile, 'ZIP_ZSTANDARD'):
    ZIP_METHODS.update((20, zipfile.ZIP_ZSTANDARD))


class RangeUnsupported(ValueError):
    """The server does not permit safe parallel ranges; use a single stream."""


def download_ranges(url, archive, job, saved, offset, connections, progress):
    """Keep only a bounded window of ranges; commit them to the ZIP in order."""
    cancel = threading.Event()
    total = saved['total']; etag = saved['etag']

    def fetch(start, end, target):
        for attempt in range(3):
            received = 0
            try:
                if cancel.is_set(): raise RuntimeError('ZIP download cancelled')
                headers = {'User-Agent': 'Vastgame/1', 'Accept-Encoding': 'identity',
                           'Range': f'bytes={start}-{end}', 'If-Range': etag}
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
                    if response.status == 200: raise RangeUnsupported('Server ignored parallel range request')
                    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                    if (response.status != 206 or not match or tuple(map(int, match.groups())) != (start, end, total)
                            or response.headers.get('ETag') != etag
                            or response.headers.get('Content-Encoding', 'identity').lower() != 'identity'
                            or urllib.parse.urlsplit(response.url).scheme not in ('http', 'https')):
                        raise RangeUnsupported('Server returned an incompatible range response')
                    with target.open('wb') as output:
                        while block := response.read(min(BLOCK, end-start+1-received)):
                            if cancel.is_set(): raise RuntimeError('ZIP download cancelled')
                            if shutil.disk_usage(job).free < len(block)+RESERVE:
                                raise ValueError('Staging disk is full; partial download kept for retry')
                            output.write(block); received += len(block)
                            if progress: progress.advance(len(block))
                        if received != end-start+1 or response.read(1): raise OSError('Incomplete or oversized range')
                return target
            except urllib.error.HTTPError as exc:
                # Rate/concurrency limits use the existing single-stream retry path.
                if exc.code in (400, 403, 405, 416, 429, 503):
                    raise RangeUnsupported('Server refused parallel downloads') from None
                raise ValueError(f'ZIP server returned HTTP {exc.code}; no game published') from None
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.IncompleteRead):
                if progress: progress.advance(-received)
                if attempt == 2: raise OSError('ZIP range download interrupted') from None
                if cancel.wait(1): raise RuntimeError('ZIP download cancelled') from None

    # One committing range can temporarily exist both in the ZIP and this window.
    if total-offset+RESERVE+RANGE_BYTES > shutil.disk_usage(job).free:
        return False
    with tempfile.TemporaryDirectory(prefix='zip-parts-', dir=job) as temporary:
        pool = ThreadPoolExecutor(max_workers=connections)
        pending = deque()
        ranges = iter(range(offset, total, RANGE_BYTES))
        def enqueue():
            start = next(ranges, None)
            if start is not None:
                target = Path(temporary)/str(start)
                pending.append(pool.submit(fetch, start, min(total-1, start+RANGE_BYTES-1), target))
        try:
            if progress: progress.phase('1/6 Downloading ZIP', total, offset, detail=f'Up to {connections} connections')
            with archive.open('ab' if offset else 'wb') as output:
                for _ in range(connections): enqueue()
                while pending:
                    target = pending.popleft().result()
                    with target.open('rb') as source:
                        while block := source.read(BLOCK):
                            if shutil.disk_usage(job).free < len(block)+RESERVE:
                                raise ValueError('Staging disk is full; partial download kept for retry')
                            output.write(block)
                    output.flush()
                    target.unlink()
                    enqueue()
            return True
        finally:
            cancel.set()
            pool.shutdown(wait=True, cancel_futures=True)


def download(url, job, progress=None, connections=8):
    if type(connections) is not int or not 1 <= connections <= 8:
        raise ValueError('Download connections must be between 1 and 8')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use a direct HTTP(S) ZIP URL without embedded account credentials')
    archive = job/'download.zip'
    metadata = job/'download.json'
    saved = json.loads(metadata.read_text()) if metadata.exists() else {}
    parallel = connections > 1
    if saved.get('complete') and archive.exists():
        if progress: progress.phase('1/6 Checking cached ZIP', archive.stat().st_size)
        if hash_file(archive, progress=progress) == saved.get('sha256'):
            return archive
    attempt = 0
    while attempt < 3:
        if progress: progress.phase('1/6 Connecting to ZIP server', detail=f'Attempt {attempt+1}/3')
        offset = archive.stat().st_size if archive.exists() else 0
        validator = saved.get('etag') or saved.get('modified')
        if not validator or offset == saved.get('total'):
            offset = 0
        headers = {'User-Agent': 'Vastgame/1', 'Accept-Encoding': 'identity'}
        if offset:
            headers.update(Range=f'bytes={offset}-', **{'If-Range': validator})
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
                if urllib.parse.urlsplit(response.url).scheme not in ('http', 'https'):
                    raise ValueError('Unsupported download redirect')
                if 'html' in response.headers.get('Content-Type', '').lower():
                    raise ValueError('Unsupported ingest format: HTML/login page, not a direct portable-game ZIP')
                status = response.status
                length = response.headers.get('Content-Length')
                total = int(length) if length else None
                etag = response.headers.get('ETag')
                if etag and etag.startswith('W/'):
                    etag = None
                modified = response.headers.get('Last-Modified')
                if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                    raise ValueError('Unexpected HTTP content encoding; no game published')
                if status == 206:
                    match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                    if not offset or not match or int(match[1]) != offset or (etag or modified) != validator:
                        raise ValueError('Server returned an unsafe resume response; retry with a fresh ZIP URL')
                    total = int(match[3])
                    if int(match[2]) != total-1:
                        raise ValueError('Incomplete HTTP range response')
                elif status == 200:
                    offset = 0
                else:
                    raise ValueError('Unexpected download response')
                if total is not None and (total < offset or total-offset+RESERVE > shutil.disk_usage(job).free):
                    raise ValueError('Not enough staging space for ZIP download and bounded upload workspace')
                saved = dict(etag=etag, modified=modified, total=total, complete=False)
                atomic(metadata, saved)
                received = offset
                if progress: progress.phase('1/6 Downloading ZIP', total, offset, detail='1 connection')
                ranged = False
                if (parallel and etag and total is not None and total-offset >= 2*RANGE_BYTES
                        and response.headers.get('Accept-Ranges', '').lower() != 'none'):
                    # HEAD/Accept-Ranges alone cannot prove a server honors every range.
                    resolved_url = response.url
                    response.close()
                    try: ranged = download_ranges(resolved_url, archive, job, saved, offset, connections, progress)
                    except RangeUnsupported:
                        parallel = False
                        continue
                    if not ranged:
                        parallel = False
                        continue
                    received = archive.stat().st_size
                if not ranged:
                    with archive.open('ab' if offset else 'wb') as output:
                        while block := response.read(BLOCK):
                            if shutil.disk_usage(job).free < len(block)+RESERVE:
                                raise ValueError('Staging disk is full; partial download kept for retry')
                            output.write(block); received += len(block)
                            if progress: progress.advance(len(block))
                if total is not None and received != total:
                    raise OSError('Incomplete download')
                with archive.open('rb') as source:
                    if source.read(4) != b'PK\x03\x04':
                        raise ValueError('Unsupported ingest format: expected a direct portable-game ZIP')
                if not zipfile.is_zipfile(archive):
                    raise ValueError('Invalid or multipart ZIP; no game published')
                if progress: progress.phase('1/6 Verifying ZIP SHA256', received)
                saved.update(complete=True, sha256=hash_file(archive, progress=progress))
                atomic(metadata, saved)
                return archive
        except urllib.error.HTTPError as exc:
            # Never print signed URL query parameters or write HTTP error pages.
            raise ValueError(f'ZIP server returned HTTP {exc.code}; no game published') from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, http.client.IncompleteRead):
            if attempt == 2:
                raise ValueError('ZIP download interrupted; staging kept. Repeat the same ingest command to resume') from None
            attempt += 1
            time.sleep(1)
    raise ValueError('Download failed')


def members(archive, job):
    records = []; seen = {}; total = 0
    with archive.open('rb') as file:
        file.seek(max(0, archive.stat().st_size-65557))
        tail = file.read()
    end = tail.rfind(b'PK\x05\x06')
    if end < 0 or len(tail)-end < 22:
        raise ValueError('Invalid ZIP directory')
    disk, central_disk, disk_entries, entries = struct.unpack_from('<4H', tail, end+4)
    if disk or central_disk or disk_entries != entries:
        raise ValueError('Multipart ZIPs are unsupported')
    if end >= 20 and tail[end-20:end-16] == b'PK\x06\x07':
        zip64_disk, _, disks = struct.unpack_from('<IQI', tail, end-16)
        if zip64_disk or disks != 1:
            raise ValueError('Multipart ZIPs are unsupported')
    with zipfile.ZipFile(archive) as source:
        if len(source.infolist()) > 200000:
            raise ValueError('ZIP contains too many entries')
        for entry in source.infolist():
            raw = entry.filename
            if '\x00' in entry.orig_filename:
                raise ValueError('Unsafe ZIP entry path')
            path = PurePosixPath(raw)
            if (not raw or '\\' in raw or ':' in raw or '\x00' in raw or path.is_absolute()
                    or '..' in path.parts or str(path) == '.'):
                raise ValueError('Unsafe ZIP entry path')
            if any(part.endswith((' ', '.')) or re.fullmatch(r'(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?', part, re.I)
                   for part in path.parts):
                raise ValueError('ZIP contains an unsafe Windows filename')
            name = str(path).casefold()
            if name in seen:
                raise ValueError('Duplicate or case-colliding ZIP entries')
            seen[name] = entry.is_dir()
            mode = entry.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or (kind and (kind == stat.S_IFDIR) != entry.is_dir()):
                raise ValueError('ZIP links and special files are unsupported')
            if entry.flag_bits & 1:
                raise ValueError('Password-protected ZIPs are unsupported')
            if entry.compress_type not in ZIP_METHODS:
                if entry.compress_type in (20, 93):
                    raise ValueError('Zstandard ZIP extraction requires Python 3.14 or newer; downloaded ZIP retained')
                raise ValueError(f'Unsupported ZIP compression method: {entry.compress_type}; downloaded ZIP retained')
            total += entry.file_size
            records.append(entry)
        for entry in records:
            for parent in PurePosixPath(entry.filename).parents:
                if str(parent).casefold() in seen and not seen[str(parent).casefold()]:
                    raise ValueError('ZIP file conflicts with a directory')
    if not total:
        raise ValueError('Empty ZIP')
    if total+RESERVE > shutil.disk_usage(job).free:
        raise ValueError('Not enough disk space to extract ZIP and retain bounded upload workspace')
    return records


def extract(archive, job, progress=None):
    destination = job/'extracted'
    receipt = job/'extraction.json'
    if progress: progress.phase('2/6 Checking ZIP SHA256', archive.stat().st_size)
    sha = hash_file(archive, progress=progress)
    if destination.is_dir() and receipt.exists() and json.loads(receipt.read_text()).get('sha256') == sha:
        return destination
    temporary = job/'extracted.tmp'
    shutil.rmtree(temporary, ignore_errors=True)
    if progress: progress.phase('2/6 Validating ZIP entries')
    records = members(archive, job)
    temporary.mkdir(mode=0o700)
    if progress: progress.phase('2/6 Extracting ZIP', sum(entry.file_size for entry in records))
    try:
        with zipfile.ZipFile(archive) as source:
            for entry in records:
                target = temporary/entry.filename
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as inp, target.open('xb') as output:
                    while block := inp.read(BLOCK):
                        output.write(block)
                        if progress: progress.advance(len(block))
                target.chmod(0o600)
        shutil.rmtree(destination, ignore_errors=True)
        temporary.rename(destination)
        atomic(receipt, dict(sha256=sha))
        return destination
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def ingest(url, catalog, cache, gid=None, exe=None, dlss=False, expected_sha=None, keep=False, connections=8):
    with Progress() as progress:
        result = _ingest(url, catalog, cache, gid, exe, dlss, expected_sha, keep, progress, connections)
        progress.phase('Import complete', 0, detail=result['id'])
    print('Imported game '+result['id']+'; start it with: vastgame start '+result['id'], flush=True)
    return result


def _ingest(url, catalog, cache, gid, exe, dlss, expected_sha, keep, progress, connections=8):
    if gid:
        valid_id(gid)
        if (catalog/gid/'manifest.json').exists():
            raise ValueError('Game already exists; no import started')
    job = cache/hashlib.sha256(url.encode()).hexdigest()
    job.mkdir(parents=True, exist_ok=True, mode=0o700)
    job.chmod(0o700)
    archive = download(url, job, progress, connections)
    if expected_sha:
        progress.phase('1/6 Checking trusted checksum', archive.stat().st_size)
    if expected_sha and hash_file(archive, progress=progress) != expected_sha:
        raise ValueError('ZIP SHA256 does not match; no game published')
    folder = extract(archive, job, progress)
    progress.phase('3/6 Detecting game and save locations')
    manifest = create(folder, gid, exe, dlss, progress)
    target = catalog/manifest['id']/'manifest.json'
    if target.exists():
        raise ValueError('Game already exists; catalog unchanged')
    staging_manifest = job/'manifest.json'
    atomic(staging_manifest, manifest)
    result = publish(staging_manifest, Path(manifest['source']['path']), job/'publication', imported=True, progress=progress)
    # The catalog becomes visible only after every remote object and commit verifies.
    atomic(target, result)
    progress.phase('6/6 Cleaning staging' if not keep else '6/6 Retaining staging')
    if not keep:
        shutil.rmtree(job)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url'); parser.add_argument('game_id', nargs='?')
    parser.add_argument('--exe', help='Executable relative to extracted ZIP root')
    parser.add_argument('--dlss', action='store_true')
    parser.add_argument('--sha256', help='Expected SHA256 of the downloaded ZIP')
    parser.add_argument('--keep-staging', action='store_true')
    parser.add_argument('--connections', type=int, choices=range(1, 9), default=8,
                        help='Parallel ZIP connections when safely supported (default: 8; 1 disables)')
    parser.add_argument('--catalog', type=Path, required=True)
    parser.add_argument('--cache', type=Path, required=True)
    args = parser.parse_args()
    if args.sha256 and not re.fullmatch('[a-fA-F0-9]{64}', args.sha256):
        parser.error('--sha256 must contain 64 hexadecimal characters')
    try:
        ingest(args.url, args.catalog, args.cache, args.game_id, args.exe, args.dlss,
               args.sha256.lower() if args.sha256 else None, args.keep_staging, args.connections)
    except KeyboardInterrupt:
        raise SystemExit('Import cancelled; catalog unchanged. Repeat the command to reuse staging')
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, EOFError, subprocess.SubprocessError) as exc:
        raise SystemExit('Game import failed: '+str(exc))


if __name__ == '__main__':
    main()
