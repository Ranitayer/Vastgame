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
         'Ensure-Desktop.ps1', 'Collect-Diagnostics.cmd', 'Collect-Diagnostics.ps1', 'WINDOWS-README.txt')


def build(output, version, commit=None, desktop=None):
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Version must be MAJOR.MINOR.PATCH')
    commit = commit or subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=PROJECT, text=True).strip()
    executable = Path(desktop) if desktop else PROJECT/'desktop/src-tauri/target/release/vastgame-desktop.exe'
    if not executable.is_file(): raise ValueError('Build the native Windows desktop before packaging; no CLI-only release will be produced')
    if executable.stat().st_size > 64*1024**2: raise ValueError('Desktop artifact exceeds the executable size limit')
    data = executable.read_bytes()
    header = int.from_bytes(data[60:64], 'little') if len(data) >= 64 else 0
    if len(data) > 64*1024**2 or data[:2] != b'MZ' or data[header:header+6] != b'PE\0\0\x64\x86':
        raise ValueError('Desktop artifact is not an x64 Windows executable')
    descriptor = json.loads(executable.with_name('desktop-build.json').read_text())
    if descriptor.get('source_commit') != commit or descriptor.get('sha256') != hashlib.sha256(data).hexdigest():
        raise ValueError('Desktop artifact and backend source do not match')
    backend = io.BytesIO()
    with gzip.GzipFile(fileobj=backend, mode='wb', mtime=0) as zipped, tarfile.open(fileobj=zipped, mode='w') as archive:
        for path in [PROJECT/'bin/vastgame', *sorted((PROJECT/'src').rglob('*'))]:
            if not path.is_file() or path.is_symlink() or not (path.suffix in ('.py', '.sh', '.cpp', '.h', '.jq') or
                path.name in ('vastgame', 'ludusavi.json.gz', 'LUDUSAVI-LICENSE', 'countries.json', 'COUNTRIES.md')):
                continue
            content = path.read_bytes()
            member = tarfile.TarInfo(path.relative_to(PROJECT).as_posix())
            member.size = len(content); member.mode = 0o755 if member.name == 'bin/vastgame' else 0o644
            archive.addfile(member, io.BytesIO(content))
    files = {name: (HERE/name).read_bytes() for name in FILES}
    files['backend.tar.gz'] = backend.getvalue()
    files['vastgame-desktop.exe'] = data
    files['desktop-build.json'] = json.dumps(dict(source_commit=commit, sha256=hashlib.sha256(data).hexdigest())).encode()
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
    parser.add_argument('--desktop', type=Path)
    args = parser.parse_args()
    build(args.output, args.version, desktop=args.desktop)
