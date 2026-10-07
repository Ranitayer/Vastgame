#!/usr/bin/env python3
"""Translate Ludusavi's known Windows save paths into portable Wine recipes."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import urllib.request

URL = 'https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/master/data/manifest.yaml'


def normalized(value):
    return re.sub(r'[^a-z0-9]', '', value.casefold())


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def compile_catalog(raw):
    # YAML is used only on the client when refreshing, never on the VM.
    import yaml
    data = yaml.load(raw, Loader=getattr(yaml, 'CSafeLoader', yaml.SafeLoader))
    if not isinstance(data, dict) or len(data) < 100:
        raise ValueError('Invalid Ludusavi catalog')
    games = {}
    for title, game in data.items():
        if not isinstance(game, dict):
            continue
        games[title] = {key: game[key] for key in
                        ('files', 'installDir', 'launch', 'steam', 'id', 'registry') if key in game}
    return dict(schema=1, source=URL, sha256=hashlib.sha256(raw).hexdigest(), games=games)


def refresh(path):
    request = urllib.request.Request(URL, headers={'User-Agent': 'Vastgame-save-discovery/1'})
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read(32 * 1024**2 + 1)
    if len(raw) > 32 * 1024**2:
        raise ValueError('Ludusavi catalog exceeds size limit')
    catalog = compile_catalog(raw)
    atomic(path, gzip.compress(json.dumps(catalog, separators=(',', ':')).encode(), mtime=0))
    return catalog


def load(path):
    with gzip.open(path, 'rb') as source:
        raw = source.read(32 * 1024**2 + 1)
    if len(raw) > 32 * 1024**2:
        raise ValueError('Ludusavi cache exceeds size limit')
    catalog = json.loads(raw)
    if catalog.get('schema') != 1 or not isinstance(catalog.get('games'), dict):
        raise ValueError('Invalid Ludusavi cache')
    return catalog


def match(manifest, catalog, title=None):
    games = catalog['games']
    if title:
        if title not in games:
            raise ValueError('Unknown Ludusavi title: ' + title)
        return title
    steam_id = manifest.get('steam', {}).get('id')
    if steam_id:
        candidates = [name for name, game in games.items() if game.get('steam', {}).get('id') == steam_id
                      or steam_id in game.get('id', {}).get('steamExtra', [])]
    else:
        aliases = {normalized(manifest.get('name', '')), normalized(manifest['id'])} - {''}
        candidates = []
        for name, game in games.items():
            known = {normalized(name), normalized(game.get('id', {}).get('lutris', ''))}
            known.update(normalized(folder) for folder in game.get('installDir', {}))
            if aliases & (known - {''}):
                candidates.append(name)
        if not candidates:
            executable = manifest['game']['executable'].casefold()
            candidates = [name for name, game in games.items() if any(
                path.startswith('<base>/') and path[7:].casefold() == executable
                for path in game.get('launch', {}))]
    if len(candidates) > 1:
        raise ValueError('Ambiguous Ludusavi match; use --title: ' + ', '.join(candidates[:10]))
    return candidates[0] if candidates else None


def recipe(path):
    prefixes = {
        '<base>': ('game', ''),
        '<home>': ('prefix', 'drive_c/users/*'),
        '<winAppData>': ('prefix', 'drive_c/users/*/AppData/Roaming'),
        '<winLocalAppData>': ('prefix', 'drive_c/users/*/AppData/Local'),
        '<winLocalAppDataLow>': ('prefix', 'drive_c/users/*/AppData/LocalLow'),
        '<winDocuments>': ('prefix', 'drive_c/users/*/Documents'),
        '<winPublic>': ('prefix', 'drive_c/users/Public'),
        '<winProgramData>': ('prefix', 'drive_c/ProgramData'),
    }
    path = path.replace('\\', '/')
    for token, (base, replacement) in prefixes.items():
        if path.startswith(token + '/'):
            pattern = (replacement + '/' + path[len(token) + 1:]).lstrip('/')
            pattern = pattern.replace('<osUserName>', '*').replace('<storeUserId>', '*')
            if '<' in pattern or '>' in pattern or '\x00' in pattern or '..' in pattern.split('/'):
                return None
            # Do not turn a remote definition into an entire game/prefix backup.
            if not pattern or pattern in ('*', '**') or str(Path(pattern)) != pattern:
                return None
            if base == 'game' and all(part in ('*', '**') for part in pattern.split('/')):
                return None
            return dict(base=base, pattern=pattern)
    return None


def discover(manifest, catalog, title=None):
    title = match(manifest, catalog, title)
    if not title:
        return None
    game = catalog['games'][title]
    recipes, unsupported = [], []
    store = manifest.get('store')
    for path, details in game.get('files', {}).items():
        conditions = details.get('when', [])
        windows = [c for c in conditions if c.get('os', 'windows') == 'windows']
        if conditions and not windows:
            continue
        if windows and store and not any(not c.get('store') or c.get('store') == store for c in windows):
            continue
        item = recipe(path)
        if item is None:
            unsupported.append(path)
            continue
        tags = details.get('tags') or ['save']
        for kind, tag in [('saves', 'save'), ('configs', 'config')]:
            if tag in tags:
                recipes.append(dict(item, kind=kind))
    registry = [key.replace('/', '\\') for key in game.get('registry', {}) if key.replace('/', '\\').startswith('HKEY_CURRENT_USER\\')]
    unsupported.extend('registry:' + key for key in game.get('registry', {}) if key.replace('/', '\\') not in registry)
    return dict(source='ludusavi', title=title, catalog_sha256=catalog['sha256'],
                recipes=recipes, registry=registry, unsupported=unsupported)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('--catalog', type=Path, default=Path(__file__).with_name('ludusavi.json.gz'))
    parser.add_argument('--refresh', action='store_true')
    parser.add_argument('--title')
    args = parser.parse_args()
    if args.refresh:
        catalog = refresh(args.catalog)
    elif args.catalog.exists():
        catalog = load(args.catalog)
    else:
        shipped = Path(__file__).with_name('ludusavi.json.gz')
        catalog = load(shipped)
        if args.catalog != shipped:
            atomic(args.catalog, shipped.read_bytes())
    manifest = json.loads(args.manifest.read_text())
    discovery = discover(manifest, catalog, args.title)
    if discovery is None:
        print('No exact Ludusavi match; existing save paths and prefix safety net retained.')
        return
    # Never overwrite user-defined paths or require a save before its first run.
    manifest.setdefault('state', {})['discovery'] = discovery
    atomic(args.manifest, (json.dumps(manifest, indent=2) + '\n').encode())
    print(f"Save discovery: {discovery['title']} ({len(discovery['recipes'])} supported paths)")
    if discovery['unsupported']:
        print('Some store/registry paths need manual configuration; inspect state.discovery.unsupported.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, ImportError) as error:
        raise SystemExit('Save discovery failed; existing manifest retained: ' + str(error))
