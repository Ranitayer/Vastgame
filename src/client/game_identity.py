"""Resolve presentation-only Steam identity without changing launch manifests."""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.parse
import urllib.request

from save_discovery import atomic, load, normalized


def app_id(value):
    return value if type(value) is int and 0 < value < 2**32 else None


def executable_title(value):
    return re.sub(r'(?:-Win64-Shipping|_Steam|_GOG)$', '', Path(value).stem, flags=re.I) if isinstance(value, str) else ''


@lru_cache(maxsize=1)
def title_index():
    index = {}
    try:
        games = load(Path(__file__).with_name('ludusavi.json.gz'))['games']
    except (OSError, ValueError, TypeError):
        return index
    for title, game in games.items():
        steam = app_id(game.get('steam', {}).get('id'))
        if not steam:
            continue
        aliases = [title, game.get('id', {}).get('lutris', ''), *game.get('installDir', {})]
        aliases += [executable_title(path) for path in game.get('launch', {}) if path.lower().endswith('.exe')]
        for alias in aliases:
            key = normalized(alias)
            if key:
                index.setdefault(key, set()).add((steam, title))
    return index


def hints(manifest, display):
    game = manifest.get('game', {})
    values = [display.get('name', ''), manifest.get('name', ''),
              executable_title(game.get('executable', '') if isinstance(game, dict) else ''), manifest.get('id', '').replace('-', ' ')]
    return list(dict.fromkeys(value.strip()[:160] for value in values if isinstance(value, str) and value.strip()))


def identity_cache():
    return Path(os.environ.get('XDG_CACHE_HOME', Path.home()/'.cache'))/'vastgame/identity'


def cache_key(terms):
    return hashlib.sha256(json.dumps(terms).encode()).hexdigest()


def cached_identity(terms, cache):
    try:
        path = cache/(cache_key(terms)+'.json')
        if path.stat().st_size > 2048:
            return None
        value = json.loads(path.read_text())
        if app_id(value.get('steam_appid')) and isinstance(value.get('name'), str) and 0 <= time.time()-value.get('updated', 0) < 30*86400:
            return dict(steam_appid=value['steam_appid'], name=value['name'][:160])
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def resolve(manifest, display=None, online=False, cache=None):
    display = dict(display) if isinstance(display, dict) else {}
    if isinstance(display.get('name'), str) and display['name'].strip():
        display['name'] = display['name'].strip()[:160]
    else:
        display.pop('name', None)
    name = (display.get('name') or manifest.get('name') or manifest['id']).strip()[:160]
    steam = manifest.get('steam', {})
    explicit = app_id(display.get('steam_appid')) or app_id(manifest.get('steam_appid')) or app_id(steam.get('id') if isinstance(steam, dict) else None)
    if explicit:
        return dict(name=name, steam_appid=explicit)
    terms = hints(manifest, display)
    index = title_index()
    for term in terms:
        matches = index.get(normalized(term), set())
        if len(matches) == 1:
            steam, title = next(iter(matches))
            return dict(name=display.get('name') or title, steam_appid=steam)
    cache = cache if cache is not None else identity_cache()
    saved = cached_identity(terms, cache)
    if saved:
        return dict(saved, name=display.get('name') or saved['name'])
    if online:
        normalized_terms = {normalized(value) for value in terms}
        for term in terms:
            try:
                url = 'https://store.steampowered.com/api/storesearch/?'+urllib.parse.urlencode(dict(term=term, l='english', cc='US'))
                request = urllib.request.Request(url, headers={'User-Agent': 'Vastgame/1'})
                with urllib.request.urlopen(request, timeout=6) as response:
                    raw = response.read(128*1024+1)
                if len(raw) > 128*1024:
                    continue
                items = json.loads(raw).get('items', [])
                candidates = {(item['id'], item['name'][:160]) for item in items if isinstance(item, dict)
                              and item.get('type') == 'app' and app_id(item.get('id')) and isinstance(item.get('name'), str)
                              and normalized(item['name']) in normalized_terms}
                if len(candidates) != 1:
                    continue
                steam, title = candidates.pop()
                result = dict(name=title, steam_appid=steam)
                try:
                    cache.mkdir(parents=True, exist_ok=True)
                    atomic(cache/(cache_key(terms)+'.json'), json.dumps(dict(result, updated=time.time())).encode())
                    files = sorted(cache.glob('*.json'), key=lambda path: path.stat().st_mtime, reverse=True)
                    for path in files[128:]:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass  # Artwork still works when the cache is temporarily unwritable.
                return dict(result, name=display.get('name') or title)
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                continue
    return dict(name=name, steam_appid=None)


def for_game(gid, catalog):
    from game_catalog import valid_id
    valid_id(gid)
    path = catalog/gid/'manifest.json'
    if path.is_symlink() or path.parent.is_symlink() or path.stat().st_size > 1024*1024:
        raise ValueError('Invalid game metadata')
    manifest = json.loads(path.read_text())
    if not isinstance(manifest, dict) or manifest.get('id') != gid or not isinstance(manifest.get('name'), str):
        raise ValueError('Game identity differs from manifest')
    presentation = catalog.parent/'library.json'
    metadata = json.loads(presentation.read_text()) if presentation.exists() else {}
    games = metadata.get('games', {}) if isinstance(metadata, dict) else {}
    display = games.get(gid, {}) if isinstance(games, dict) else {}
    return resolve(manifest, display, online=True)
