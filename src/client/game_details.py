"""Cache public Steam descriptions, credits and review summaries for the library."""
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from html.parser import HTMLParser
from urllib.request import urlopen


class PlainText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def text(value, limit=2000):
    parser = PlainText()
    parser.feed(value if isinstance(value, str) else '')
    return ' '.join(' '.join(parser.parts).split())[:limit]


def names(value):
    return [text(name, 120) for name in value[:10] if isinstance(name, str)] if isinstance(value, list) else []


def fetch(url):
    with urlopen(url, timeout=8) as response:
        raw = response.read(512 * 1024 + 1)
    if len(raw) > 512 * 1024:
        raise ValueError('Steam response too large')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Invalid Steam response')
    return value


def details(appid, cache):
    if not str(appid).isdigit() or not 0 < int(appid) < 2**32:
        raise ValueError('Invalid Steam app ID')
    appid = str(int(appid))
    target = cache / f'{appid}.json'
    cached = None
    try:
        if target.stat().st_size <= 32 * 1024:
            saved = json.loads(target.read_text())
            if isinstance(saved.get('details'), dict):
                cached = saved
                if 0 <= time.time() - saved.get('updated', 0) < 86400:
                    return saved['details']
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    result = dict(description='', developers=[], publishers=[], reviews=None)
    complete = True
    try:
        data = fetch(f'https://store.steampowered.com/api/appdetails?appids={appid}&l=english')[appid]
        if data.get('success'):
            data = data['data']
            result.update(description=text(data.get('short_description')),
                          developers=names(data.get('developers')),
                          publishers=names(data.get('publishers')))
        else:
            complete = False
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        complete = False
    try:
        data = fetch(f'https://store.steampowered.com/appreviews/{appid}?json=1&language=all&purchase_type=all&filter=all&num_per_page=0')
        summary = data.get('query_summary', {})
        total, positive = summary.get('total_reviews'), summary.get('total_positive')
        if data.get('success') == 1 and type(total) is int and type(positive) is int and 0 <= positive <= total:
            result['reviews'] = dict(total=total, positive=positive, sentiment=text(summary.get('review_score_desc'), 80))
        else:
            complete = False
    except (OSError, ValueError, TypeError, AttributeError):
        complete = False
    if complete:
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', dir=cache, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(dict(updated=time.time(), details=result), handle)
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
    elif cached:
        return cached['details']
    return result


if __name__ == '__main__':
    try:
        cache = Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'vastgame' / 'metadata'
        print(json.dumps({'details': details(sys.argv[1], cache)}))
    except (OSError, ValueError, IndexError):
        print(json.dumps({'details': None}))
