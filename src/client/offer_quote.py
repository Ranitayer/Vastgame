"""Read one exact offer at game-specific storage; never create a rental."""
import json
import math
from pathlib import Path
import re
import subprocess
import sys
from disk_capacity import required_disk_gb

ROOT = Path(__file__).resolve().parents[2]

class OfferError(ValueError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.error = dict(code=code, message=message, **details)


def validate(offer, disk, approved=None):
    issue = subprocess.run(['jq', '-L', str(ROOT/'src/providers/vast'), 'include "eligibility"; compatibility_error'],
                           input=json.dumps(offer), capture_output=True, text=True, timeout=5)
    if issue.returncode:
        raise OfferError('RESPONSE_INVALID', 'Cannot validate the provider response; no VM rented')
    error = json.loads(issue.stdout)
    if error:
        raise OfferError(error.pop('code'), error.pop('message'), **error)
    if offer.get('num_gpus') != 1:
        raise OfferError('GPU_COUNT_UNSUPPORTED', 'Choose an offer with one GPU')
    if offer.get('rentable') is not True:
        raise OfferError('OFFER_UNAVAILABLE', 'Offer no longer available. Refresh Hosts')
    if (offer.get('direct_port_count') or 0) < 1:
        raise OfferError('PORTS_UNAVAILABLE', 'This offer has no direct streaming ports')
    available = offer.get('disk_space')
    if type(available) not in (int, float) or not math.isfinite(available):
        raise OfferError('DISK_UNKNOWN', 'Provider did not report disk capacity. Choose another rig')
    if available < disk:
        raise OfferError('DISK_INSUFFICIENT', f'Disk insufficient: needs {disk} GB; rig has {available:g} GB', required=disk, available=available)
    price = offer.get('dph_total')
    if type(price) not in (int, float) or not math.isfinite(price) or price < 0:
        raise OfferError('PRICE_UNKNOWN', 'Provider did not return a valid hourly price')
    if approved is not None and price > approved + 1e-9:
        raise OfferError('PRICE_INCREASED', f'Price increased: approved ${approved:.4f}/h; current ${price:.4f}/h. Confirm the new quote before renting', approved=approved, current=price, disk_gb=disk)
    return dict(offer_id=offer['id'], machine_id=offer.get('machine_id'), price=price, disk_gb=disk)


def fetch_offers(disk, machine_id=0, timeout=60):
    # The bundles endpoint's id filter does not match its returned ask IDs.
    # Preserve the rentable single-GPU VM query, then match the returned ID locally.
    query = 'num_gpus=1 verified=any rentable=true vms_enabled=true'
    if machine_id: query += f' machine_id={machine_id}'
    try:
        result = subprocess.run(['vastai', 'search', 'offers', query, '--storage', str(disk), '--limit', '10000', '--order', 'dph_total', '--raw'], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise OfferError('API_TIMEOUT', 'Vast offer lookup timed out. Retry; no VM rented')
    except OSError:
        raise OfferError('BACKEND_UNAVAILABLE', 'Vast CLI unavailable. Check your installation')
    if result.returncode:
        if re.search(r'\b(401|403)\b|unauthorized|invalid api key', result.stderr + result.stdout, re.I):
            raise OfferError('AUTH_FAILED', 'Vast rejected your credentials. Check your API key')
        raise OfferError('API_FAILED', 'Vast offer lookup failed. Retry; no VM rented')
    try:
        offers = json.loads(result.stdout)
    except ValueError:
        raise OfferError('RESPONSE_INVALID', 'Vast returned invalid offer data. Retry')
    if not isinstance(offers, list) or len(result.stdout) > 16*1024*1024:
        raise OfferError('RESPONSE_INVALID', 'Vast returned invalid offer data. Retry')
    return offers


def fetch(offer_id, disk, machine_id=0):
    offers = fetch_offers(disk, machine_id)
    matches = [offer for offer in offers if isinstance(offer, dict) and offer.get('id') == offer_id]
    if len(matches) != 1:
        if len(offers) >= 10000:
            raise OfferError('OFFER_UNVERIFIED', 'Offer lookup reached the response limit. Refresh Hosts and choose again')
        raise OfferError('OFFER_UNAVAILABLE', 'Offer no longer available. Refresh Hosts')
    return matches[0]


def quote(manifest, offer_id, machine_id=0, approved=None):
    try: disk = required_disk_gb(json.loads(manifest.read_text()))
    except (OSError, ValueError, TypeError, AttributeError):
        raise OfferError('GAME_UNPACKAGED', 'Package this game first; safe disk sizing is unavailable')
    offer = fetch(offer_id, disk, machine_id)
    return validate(offer, disk, approved), offer


if __name__ == '__main__':
    try:
        manifest, oid, machine, *extra = sys.argv[1:]
        offer_id, machine_id = int(oid), int(machine)
        if offer_id <= 0 or machine_id < 0: raise ValueError('Invalid offer identity')
        approved = float(extra[0]) if extra else None
        if approved is not None and (not math.isfinite(approved) or approved < 0): raise ValueError('Invalid price')
        public, raw = quote(Path(manifest), offer_id, machine_id, approved)
        if len(extra) == 2: Path(extra[1]).write_text(json.dumps([raw]))
        print(json.dumps(dict(quote=public)))
    except OfferError as exc:
        print(json.dumps(dict(error=exc.error)))
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        print(json.dumps(dict(error=dict(code='REQUEST_INVALID', message='Cannot validate this game and offer request'))))
