"""Fetch public Steam artwork into a bounded local cache; never access game packages."""
import base64
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import urllib.request
import urllib.parse

MAX_IMAGE = 2 * 1024 * 1024
CACHE_LIMIT = 64 * 1024 * 1024


def image_type(data):
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'image/webp'
    return None


def modern_asset_url(appid, kind):
    payload = dict(ids=[{'appid': int(appid)}], context={'language': 'english', 'country_code': 'US'},
                   data_request={'include_assets': True})
    url = 'https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?' + urllib.parse.urlencode({'input_json': json.dumps(payload)})
    with urllib.request.urlopen(url, timeout=6) as response:
        raw = response.read(128 * 1024 + 1)
    if len(raw) > 128 * 1024:
        raise ValueError('Artwork metadata too large')
    items = json.loads(raw).get('response', {}).get('store_items', [])
    item = next((item for item in items if item.get('appid') == int(appid)), {})
    assets = item.get('assets', {})
    filename = assets.get('library_capsule' if kind == 'cover' else 'library_hero', '')
    if not isinstance(filename, str) or not re.fullmatch(r'(?:[a-f0-9]{40}/)?[A-Za-z0-9_-]+\.(?:jpg|png|webp)', filename):
        raise ValueError('Missing artwork asset')
    return f'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{int(appid)}/{filename}'


def artwork(appid, kind, cache):
    if not str(appid).isdigit() or not 0 < int(appid) < 2**32 or kind not in ('cover', 'banner'):
        raise ValueError('Invalid artwork request')
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f'{int(appid)}-{kind}.image'
    try:
        data = target.read_bytes() if target.stat().st_size <= MAX_IMAGE else b''
    except OSError:
        data = b''
    mime = image_type(data)
    if not mime:
        names = ('library_600x900.jpg', 'library_600x900_2x.jpg', 'library_600x900.png', 'library_600x900_2x.png') if kind == 'cover' else ('library_hero.jpg', 'header.jpg')
        urls = [f'https://cdn.akamai.steamstatic.com/steam/apps/{int(appid)}/{name}' for name in names]
        try:
            urls.insert(0, modern_asset_url(appid, kind))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass
        for url in urls:
            try:
                with urllib.request.urlopen(url, timeout=6) as response:
                    data = response.read(MAX_IMAGE + 1)
                mime = image_type(data) if len(data) <= MAX_IMAGE else None
                if not mime:
                    continue
                descriptor, temporary = tempfile.mkstemp(dir=cache, prefix='.art-')
                try:
                    with os.fdopen(descriptor, 'wb') as output:
                        output.write(data)
                    os.replace(temporary, target)
                finally:
                    Path(temporary).unlink(missing_ok=True)
                break
            except (OSError, ValueError):
                mime = None
    if not mime:
        return {'image': None}
    # Only dispose artwork files in this dedicated cache, never catalog or save data.
    files = []
    for path in cache.glob('*.image'):
        try:
            info = path.stat()
            files.append((info.st_mtime, info.st_size, path))
        except FileNotFoundError:
            pass
    files.sort()
    total = sum(size for _, size, _ in files)
    for _, size, path in files:
        if total <= CACHE_LIMIT:
            break
        if path != target:
            try:
                path.unlink()
                total -= size
            except FileNotFoundError:
                pass
    return {'image': f'data:{mime};base64,' + base64.b64encode(data).decode('ascii')}


if __name__ == '__main__':
    try:
        cache = Path(os.environ.get('XDG_CACHE_HOME', str(Path.home()/'.cache'))) / 'vastgame/artwork'
        if sys.argv[1] == '--game':
            if sys.argv[3] not in ('cover', 'banner'):
                raise ValueError('Invalid artwork kind')
            from game_identity import for_game
            catalog = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'vastgame/games'
            identity = for_game(sys.argv[2], catalog)
            result = artwork(identity['steam_appid'], sys.argv[3], cache) if identity['steam_appid'] else {'image': None}
            print(json.dumps(dict(result, identity=identity)))
        else:
            print(json.dumps(artwork(sys.argv[1], sys.argv[2], cache)))
    except (OSError, ValueError, IndexError):
        print(json.dumps({'image': None}))
