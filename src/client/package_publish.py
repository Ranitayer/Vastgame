#!/usr/bin/env python3
"""Publish immutable game parts; commit the local package pointer last."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile


def hash_file(path, algorithm='sha256'):
    h = hashlib.new(algorithm)
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def publish(manifest, archive, parts_dir, unpacked, remote='gdrive:VastGaming'):
    m = json.loads(manifest.read_text())
    sha = hash_file(archive)
    base = f'games/{m["id"]}/{sha}'
    parts = [dict(name=p.name, size=p.stat().st_size, sha256=hash_file(p))
             for p in sorted(parts_dir.glob('part-*'))]
    # Drive exposes MD5 for ordinary objects: verify all parts without downloading
    # the entire game again. SHA256 remains the VM's end-to-end integrity check.
    expected = {p.name: hash_file(p, 'md5') for p in sorted(parts_dir.glob('part-*'))}
    print(f'Uploading {len(parts)} verified parts ({archive.stat().st_size / 1024**3:.2f} GiB)', flush=True)
    subprocess.run(['rclone', 'copy', str(parts_dir), remote+'/'+base+'/parts',
                    '--immutable', '--checksum', '--no-update-modtime', '--transfers', '8',
                    '--checkers', '8', '--drive-chunk-size', '64M', '--progress', '--stats-one-line'], check=True)
    rows = subprocess.check_output(['rclone', 'hashsum', 'MD5', remote+'/'+base+'/parts'], text=True)
    actual = {line.split(None, 1)[1].strip(): line.split(None, 1)[0].lower()
              for line in rows.splitlines() if len(line.split(None, 1)) == 2}
    if actual != expected:
        raise ValueError('Remote package part verification failed; local manifest unchanged')
    m.setdefault('version', 'v1')  # save-format version is independent of binary identity
    m['package'] = dict(version=sha, archive=base+'/game.tar.zst', checksum=base+'/game.tar.zst.sha256',
                        sha256=sha, size=archive.stat().st_size,
                        unpacked_bytes=int(unpacked), parts=parts)
    with tempfile.TemporaryDirectory() as tmp:
        checksum = Path(tmp)/'game.tar.zst.sha256'; checksum.write_text(sha+'  game.tar.zst\n')
        committed = Path(tmp)/'COMMITTED.json'; committed.write_text(json.dumps(m['package'], sort_keys=True))
        for file in (checksum, committed):
            subprocess.run(['rclone', 'copyto', str(file), remote+'/'+base+'/'+file.name,
                            '--immutable', '--checksum', '--no-update-modtime'], check=True)
            readback = subprocess.check_output(['rclone', 'cat', remote+'/'+base+'/'+file.name])
            if readback != file.read_bytes():
                raise ValueError('Remote package commit verification failed')
    pending = manifest.with_suffix('.json.tmp')
    pending.write_text(json.dumps(m, indent=2)+'\n'); pending.replace(manifest)


if __name__ == '__main__':
    publish(*map(Path, sys.argv[1:4]), int(sys.argv[4]))
