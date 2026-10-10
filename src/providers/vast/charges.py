"""Bounded read-only Vast charges lookup; never expose account credentials."""
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api_key():
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'vastai/vast_api_key'
    path = config if config.exists() else Path.home()/'.vast_api_key'
    if path.stat().st_size > 16384: raise ValueError('Vast account key is invalid')
    key = path.read_text().strip()
    if not key or any(char.isspace() for char in key): raise ValueError('Vast account key is invalid')
    return key


def fetch_charges(start, end):
    if not 0 < start <= end: raise ValueError('Unknown billing time range')
    deadline = time.monotonic() + 30
    token, seen, rows, size = None, set(), [], 0
    # Charges are grouped by UTC day; include both boundary days in full.
    params = dict(select_filters=json.dumps(dict(day=dict(gte=start//86400*86400,
                                                         lte=(end//86400+1)*86400), type={'in': ['instance']})),
                  format='table', limit='200', latest_first='false')
    try: key = api_key()
    except OSError: raise ValueError('Vast account key unavailable; configure account access') from None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        for _ in range(20):
            remaining = deadline-time.monotonic()
            if remaining <= 0: raise ValueError('Vast charge lookup timed out; retry refresh')
            if token: params['after_token'] = token
            request = urllib.request.Request('https://console.vast.ai/api/v0/charges/?'+urllib.parse.urlencode(params),
                                             headers={'Authorization': 'Bearer '+key, 'Accept': 'application/json'})
            with opener.open(request, timeout=min(10, remaining)) as response:
                chunks, received = [], 0
                while received <= 2*1024*1024:
                    if time.monotonic() >= deadline: raise ValueError('Vast charge lookup timed out; retry refresh')
                    chunk = response.read1(min(65536, 2*1024*1024+1-received))
                    if not chunk: break
                    chunks.append(chunk); received += len(chunk)
                raw = b''.join(chunks)
            size += len(raw)
            if len(raw) > 2*1024*1024 or size > 8*1024*1024: raise ValueError('Vast charge response exceeded its limit')
            page = json.loads(raw, parse_float=Decimal)
            if not isinstance(page, dict) or page.get('success') is not True or not isinstance(page.get('results'), list) or 'next_token' not in page:
                raise ValueError('Vast returned invalid charge data')
            if page.get('count') != len(page['results']): raise ValueError('Vast charge page is incomplete')
            rows.extend(page['results'])
            token = page['next_token']
            if token is None:
                if type(page.get('total')) is not int or page['total'] > len(rows): raise ValueError('Vast charge history is incomplete')
                return rows
            if not isinstance(token, str) or not token or len(token) > 4096 or token in seen:
                raise ValueError('Vast charge pagination is invalid')
            seen.add(token)
        raise ValueError('Vast charge history exceeds the page limit; refresh a shorter session')
    except urllib.error.HTTPError as exc:
        raise ValueError('Vast charge access denied; check account permissions' if exc.code in (401, 403)
                         else 'Vast charge API unavailable; retry refresh') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError('Vast charge lookup unavailable or timed out; retry refresh') from None
    except (json.JSONDecodeError, UnicodeError):
        raise ValueError('Vast returned invalid charge data') from None


def money(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)): raise ValueError('Invalid Vast charge amount')
    try: amount = Decimal(str(value))
    except InvalidOperation: raise ValueError('Invalid Vast charge amount') from None
    if not amount.is_finite() or abs(amount) > Decimal('1000000000000'):
        raise ValueError('Invalid Vast charge amount')
    return amount


def session_charges(rows, instance, label):
    total, breakdown, seen, intervals, matched = Decimal(0), {}, set(), {}, 0
    def leaves(items, depth=0):
        if not isinstance(items, list) or len(items) > 2000 or depth > 8: raise ValueError('Invalid Vast charge breakdown')
        for item in items:
            if not isinstance(item, dict): raise ValueError('Invalid Vast charge breakdown')
            children = item.get('items', [])
            if children: leaves(children, depth+1)
            else:
                kind = item.get('type')
                if not isinstance(kind, str) or len(kind) > 64: raise ValueError('Invalid Vast charge type')
                breakdown[kind] = breakdown.get(kind, Decimal(0)) + money(item.get('amount'))
    for row in rows:
        if not isinstance(row, dict): raise ValueError('Invalid Vast charge row')
        if row.get('type') != 'instance' or row.get('source') != 'instance-'+instance: continue
        metadata = row.get('metadata', {})
        if not isinstance(metadata, dict) or metadata.get('label') not in (None, '', label):
            raise ValueError('Vast charge label differs from this session')
        identity = json.dumps(row, sort_keys=True, allow_nan=False, default=str)
        if identity in seen: continue
        seen.add(identity)
        start, end = row.get('start'), row.get('end')
        start, end = money(start), money(end)
        if not 0 < start <= end:
            raise ValueError('Invalid Vast charge interval')
        if (start, end) in intervals or any(start < old_end and end > old_start for old_start, old_end in intervals):
            raise ValueError('Vast charge intervals overlap; totals are ambiguous')
        intervals[(start, end)] = True
        total += money(row.get('amount')); matched += 1
        leaves(row.get('items', []))
    if not matched: return dict(status='pending', error='Charges for this instance are not published yet')
    return dict(status='reported', currency='USD', reported_usd=str(total),
                breakdown_usd={key: str(value) for key, value in sorted(breakdown.items())},
                breakdown_complete=bool(breakdown) and abs(sum(breakdown.values())-total) <= Decimal('0.000001'),
                rows=matched, final=False)
