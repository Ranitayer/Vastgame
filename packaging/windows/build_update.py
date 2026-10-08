#!/usr/bin/env python3
"""Build the public Vastgame Windows installer/update without private account data."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
FILES = ('update-backend.sh', 'apply_update.py', 'Update-Vastgame.ps1', 'Update-Vastgame.cmd',
         'Check-Updates.ps1', 'Install-Vastgame.ps1', 'Vastgame.cmd', 'run-vastgame.sh',
         'windows-bridge.sh', 'Native-Screen.ps1', 'Native-Ping.ps1', 'stream.json',
         'Edit-Stream-Settings.cmd', 'Edit-Stream-Settings.ps1', 'Complete-Setup.ps1', 'Prepare-WSL.ps1',
         'prepare-network.sh', 'install-backend.sh', 'dependencies.json',
         'Collect-Diagnostics.cmd', 'Collect-Diagnostics.ps1', 'WINDOWS-README.txt')


def build(output, version, commit=None):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Version must be MAJOR.MINOR.PATCH')
    commit = commit or subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=PROJECT, text=True).strip()
    backend = io.BytesIO()
    with gzip.GzipFile(fileobj=backend, mode='wb', mtime=0) as zipped, tarfile.open(fileobj=zipped, mode='w') as archive:
        for path in [PROJECT/'bin/vastgame', *sorted((PROJECT/'src').rglob('*'))]:
            if not path.is_file() or path.is_symlink() or not (path.suffix in ('.py', '.sh', '.cpp', '.jq') or
                path.name in ('vastgame', 'ludusavi.json.gz', 'LUDUSAVI-LICENSE')):
                continue
            content = path.read_bytes()
            member = tarfile.TarInfo(path.relative_to(PROJECT).as_posix())
            member.size = len(content); member.mode = 0o755 if member.name == 'bin/vastgame' else 0o644
            archive.addfile(member, io.BytesIO(content))
    files = {name: (HERE/name).read_bytes() for name in FILES}
    files['backend.tar.gz'] = backend.getvalue()
    files['release.json'] = json.dumps(dict(schema=1, version=version, source_commit=commit,
        files={name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())}), indent=2).encode()
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo('Vastgame/'+name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    output.with_suffix(output.suffix+'.sha256').write_text(hashlib.sha256(output.read_bytes()).hexdigest()+'  '+output.name+'\n')
    print(f'{output}: {output.stat().st_size/1024**2:.2f} MiB; public code only')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    build(args.output, args.version)
