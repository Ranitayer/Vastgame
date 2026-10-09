"""Shared portable Windows game detection, manifest creation and validation."""
import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'runtime'))
from game_session import validate
from multipart_restore import package_parts
from disk_capacity import required_disk_gb

EXCLUDED = re.compile(r'^(setup|install|unins|uninstall|vc_redist|vcredist|dxsetup|'
                      r'crashreport|unitycrashhandler|easyanticheat|launcherprereq)', re.I)


def atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(data, indent=2)+'\n')
    tmp.chmod(0o600)
    tmp.replace(path)


def valid_id(gid):
    if not isinstance(gid, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', gid):
        raise ValueError('Invalid game ID')


def portable_exe(path):
    if EXCLUDED.match(path.name) or any(p.lower() in ('redist', '_commonredist', 'prerequisites') for p in path.parts):
        return False
    with path.open('rb') as source:
        header = source.read(64)
        if len(header) < 64 or header[:2] != b'MZ':
            return False
        source.seek(int.from_bytes(header[60:64], 'little'))
        return source.read(4) == b'PE\0\0'


def detect(folder, explicit=None, progress=None):
    folder = Path(folder).resolve(strict=True)
    candidates = []
    for path in folder.rglob('*'):
        if path.is_file() and path.suffix.lower() == '.exe' and portable_exe(path):
            if not path.resolve().is_relative_to(folder):
                raise ValueError('Executable escapes source folder')
            score = 100 if '-win64-shipping' in path.name.lower() else 0
            score += 50 if path.with_name(path.stem+'_Data').is_dir() else 0
            score += 20 if any(p.lower() in ('win64', 'x64') for p in path.parts) else 0
            candidates.append((score, path))
    candidates.sort(key=lambda item: (-item[0], item[1].relative_to(folder).as_posix()))
    if not candidates:
        raise ValueError('No portable Windows game executable found; installers are unsupported')
    if explicit:
        selected = (folder/explicit).resolve(strict=True)
        if selected not in [p.resolve() for _, p in candidates]:
            raise ValueError('--exe must identify a portable game executable inside the source')
    elif len(candidates) == 1:
        selected = candidates[0][1]
    else:
        with progress.pause() if progress else nullcontext():
            print('Multiple plausible game executables:', flush=True)
            for i, (_, path) in enumerate(candidates, 1):
                print(f'  {i}. {path.relative_to(folder)}', flush=True)
            if not sys.stdin.isatty():
                raise ValueError('Ambiguous executable; retry with --exe PATH. No game published')
            answer = input('Choose executable number (or q to cancel): ').strip()
            if not answer.isdecimal() or not 1 <= int(answer) <= len(candidates):
                raise ValueError('Import cancelled; no game published')
            selected = candidates[int(answer)-1][1]
    root = folder
    # Peel wrapper folders only while they contain the entire package.
    while True:
        children = [p for p in root.iterdir() if p.name != '__MACOSX']
        if len(children) != 1 or not children[0].is_dir():
            break
        root = children[0]
    if not selected.is_relative_to(root):
        root = folder
    return root, selected.relative_to(root).as_posix()


def check(manifest, source=None):
    validate(manifest)
    if not isinstance(manifest.get('name'), str) or not manifest['name'].strip():
        raise ValueError('Missing game name')
    if manifest.get('package', {}).get('parts'):
        package_parts(manifest)
    source = source or manifest.get('source', {}).get('path')
    if source:
        root = Path(source).resolve(strict=True)
        exe = root/manifest['game']['executable']
        if not exe.resolve(strict=True).is_relative_to(root) or not portable_exe(exe):
            raise ValueError('Game executable is missing, unsafe or not a portable Windows executable')
    elif manifest.get('package'):
        package_parts(manifest)
    else:
        raise ValueError('Manifest has neither a source nor a published package')


def create(folder, gid=None, executable=None, dlss=False, progress=None):
    root, exe = detect(folder, executable, progress)
    name = root.name
    if name in ('extracted', 'extracted.tmp'):
        name = Path(exe).stem
    gid = gid or re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    valid_id(gid)
    m = dict(schema=1, id=gid, name=name, version='v1', source={'path':str(root)},
             game=dict(executable=exe, working_dir='' if Path(exe).parent == Path('.') else Path(exe).parent.as_posix(), arguments=[]),
             runner=dict(type='wine', version='ge-proton'), environment={},
             state=dict(saves=[], configs=[], shaders=[]), compatibility={'nvidia_ngx':dlss})
    check(m)
    try:
        from save_discovery import discover, load
        discovery = discover(m, load(Path(__file__).with_name('ludusavi.json.gz')))
        if discovery:
            m['state']['discovery'] = discovery
    except (OSError, ValueError, ImportError) as exc:
        print(f'Save discovery unavailable: {exc}; prefix safety remains enabled', file=sys.stderr)
    return m


def library_summary(catalog, selected_file):
    from game_identity import resolve
    try:
        selected = selected_file.read_text().strip()
    except FileNotFoundError:
        selected = ''
    presentation = catalog.parent/'library.json'
    metadata = json.loads(presentation.read_text()) if presentation.exists() else {}
    overrides = metadata.get('games', {}) if isinstance(metadata, dict) else {}
    if not isinstance(overrides, dict):
        raise ValueError('Invalid library presentation metadata')
    games, skipped = [], 0
    for path in sorted(catalog.glob('*/manifest.json')):
        try:
            if path.is_symlink() or path.parent.is_symlink():
                raise ValueError('Linked manifest')
            with path.open() as file:
                raw = file.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValueError('Manifest too large')
            manifest = json.loads(raw)
            if not isinstance(manifest, dict):
                raise ValueError('Invalid manifest')
            gid = manifest.get('id')
            valid_id(gid)
            if gid != path.parent.name or not isinstance(manifest.get('name'), str) or not manifest['name'].strip():
                raise ValueError('Invalid catalog entry')
            package = manifest.get('package', {})
            runner = manifest.get('runner', {})
            compatibility = manifest.get('compatibility', {})
            if not all(isinstance(value, dict) for value in (package, runner, compatibility)):
                raise ValueError('Invalid metadata')
            text = lambda value, limit: value[:limit] if isinstance(value, str) else ''
            size = lambda key: package.get(key) if type(package.get(key)) is int and package[key] > 0 else None
            display = overrides.get(gid, {})
            if not isinstance(display, dict):
                display = {}
            identity = resolve(manifest, display)
            packaged = bool(size('size') and re.fullmatch(r'[0-9a-fA-F]{64}', str(package.get('sha256', ''))))
            if not packaged and package.get('parts'):
                try:
                    packaged = bool(package_parts(manifest))
                except (ValueError, TypeError, KeyError):
                    pass
            try:
                disk_gb = required_disk_gb(manifest)
            except (ValueError, TypeError):
                disk_gb = None
            games.append(dict(id=gid, name=identity['name'], steam_appid=identity['steam_appid'],
                version=text(manifest.get('version', ''), 40), selected=gid == selected,
                packaged=packaged,
                required_disk_gb=disk_gb, download_bytes=size('size'), installed_bytes=size('unpacked_bytes'),
                runner=text(runner.get('version'), 80) or text(runner.get('type'), 80) or 'Not reported',
                nvidia_compatibility=compatibility.get('nvidia_ngx') is True))
        except (OSError, ValueError, TypeError):
            skipped += 1
    return dict(games=sorted(games, key=lambda game: (game['name'].casefold(), game['id'])), skipped=skipped)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    add = commands.add_parser('add')
    add.add_argument('folder', type=Path); add.add_argument('game_id', nargs='?')
    add.add_argument('--exe'); add.add_argument('--dlss', action='store_true')
    add.add_argument('--catalog', type=Path, required=True)
    verify = commands.add_parser('validate'); verify.add_argument('manifest', type=Path)
    verify.add_argument('--id')
    listing = commands.add_parser('list')
    listing.add_argument('--catalog', type=Path, required=True)
    listing.add_argument('--selected', type=Path, required=True)
    a = parser.parse_args()
    try:
        if a.command == 'list':
            print(json.dumps(library_summary(a.catalog, a.selected)))
        elif a.command == 'validate':
            m = json.loads(a.manifest.read_text())
            if a.id and m.get('id') != a.id:
                raise ValueError('Manifest ID differs from its catalog entry')
            check(m)
        else:
            if a.game_id:
                valid_id(a.game_id)
                if (a.catalog/a.game_id/'manifest.json').exists():
                    raise ValueError('Game already exists')
            m = create(a.folder, a.game_id, a.exe, a.dlss)
            target = a.catalog/m['id']/'manifest.json'
            if target.exists(): raise ValueError('Game already exists')
            atomic(target, m)
            print('Added game '+m['id'])
    except (OSError, ValueError) as exc:
        raise SystemExit('Game catalog failed: '+str(exc))
