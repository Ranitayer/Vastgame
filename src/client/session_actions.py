"""Prepare an exact historical rig for the existing desktop launch controller."""
import json
import math
import os
import re
import sys
import uuid
from pathlib import Path
import desktop_launch as desktop
import session_history as history
from game_catalog import library_summary
from offer_quote import OfferError, fetch_offers, validate
from disk_capacity import required_disk_gb


def candidate(record, game, manifest):
    rig = record.get('rig', {})
    machine = rig.get('machine_id')
    gpu = rig.get('gpu_name')
    try: rate = float(record.get('hourly_price_usd'))
    except (TypeError, ValueError): rate = -1
    if type(machine) is not int or machine <= 0 or not gpu or not math.isfinite(rate) or rate < 0:
        raise OfferError('HISTORY_INCOMPLETE', 'Previous rig or price is unknown. Choose a rig on Home')
    try: disk = required_disk_gb(json.loads(manifest.read_text()))
    except (OSError, ValueError, TypeError):
        raise OfferError('GAME_UNPACKAGED', 'Package this game first')
    offers = fetch_offers(disk, machine, timeout=45)
    ceiling = rate * 1.10
    eligible = []
    for offer in offers:
        if not isinstance(offer, dict) or offer.get('machine_id') != machine or offer.get('gpu_name') != gpu: continue
        if type(offer.get('id')) is not int or offer['id'] <= 0: continue
        try:
            validate(offer, disk, ceiling)
            eligible.append(offer)
        except OfferError: continue
    if not eligible:
        raise OfferError('PREVIOUS_RIG_UNAVAILABLE', 'Previous rig unavailable near its old price. Choose a rig on Home')
    selected = min(eligible, key=lambda offer: (offer['dph_total'], offer['id']))
    sys.path.insert(0, str(desktop.ROOT/'src/providers/vast'))
    from desktop_hosts import summarize
    return dict(game=game, rig=summarize([selected])[0], max_price=ceiling, launch=None)


def prepare(label, shutdown=False):
    record = history.read(label)
    if record.get('history_deleted'): raise OfferError('HISTORY_DELETED', 'Session history was deleted. Use Home to manage any active rig')
    game_id = record.get('game_id', '')
    rows = desktop.instance_rows()
    active = desktop.current(rows=rows)
    if active:
        job = json.loads((desktop.STATE/active['jobId']/'job.json').read_text())
        if job.get('label') != label:
            raise OfferError('ANOTHER_RIG_ACTIVE', 'Another rig is active. Use Home to manage it first')
        return dict(launch=active)
    instance = record.get('instance_id')
    matches = [row for row in rows if isinstance(row, dict) and row.get('label') == label and
               (instance is None or str(row.get('id')) == instance)]
    if len(matches) > 1:
        raise OfferError('IDENTITY_AMBIGUOUS', 'Cannot verify this exact rig; no operation started')
    if matches:
        if record.get('ended_at') or record.get('outcome') == 'stopped':
            raise OfferError('IDENTITY_CONFLICT', 'Closed session still appears online. Refresh before reconnecting')
        row = matches[0]
        if not str(row.get('id', '')).isdecimal(): raise ValueError('Invalid provider identity')
        if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', game_id):
            raise OfferError('GAME_UNKNOWN', 'Game identity is unknown; use the CLI to manage this rig')
        # CLI sessions use the same private job format; adoption never creates a VM.
        desktop.STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
        with history.locked(label):
            record = history.read(label)
            if record.get('ended_at') or record.get('force_shutdown'):
                raise OfferError('SHUTDOWN_PENDING', 'Shutdown must be confirmed before reconnecting')
            job_id = record.get('job_id')
            path = desktop.STATE/job_id/'job.json' if isinstance(job_id, str) and re.fullmatch(r'[a-f0-9]{32}', job_id) else None
            if path and path.is_file():
                job = json.loads(path.read_text())
                if job.get('label') != label or job.get('stopped'):
                    raise OfferError('IDENTITY_CONFLICT', 'Session job identity differs; no operation started')
            else:
                job_id = uuid.uuid4().hex
                folder = desktop.STATE/job_id
                folder.mkdir(mode=0o700)
                desktop.json_write(folder/'job.json', dict(job=job_id, label=label, game=game_id,
                    instance_id=str(row['id']), started_at=record.get('started_at') or 0,
                    finished=True, success=False, game_running=False, phase='Rig retained'))
                record['job_id'] = job_id
                history.write(history.folder(label)/'session.json', record)
        history.attach(row)
        result = desktop.current(job_id, rows=rows)
        if not result: raise OfferError('SESSION_CHANGED', 'Rig state changed. Refresh before reconnecting')
        return dict(launch=result)
    if any(isinstance(row, dict) and str(row.get('label', '')).startswith('vastgame-') for row in rows):
        raise OfferError('ANOTHER_RIG_ACTIVE', 'Another rig is active. Use Home to manage it first')
    if not instance and not record.get('ended_at') and record.get('creation_requested_at'):
        raise OfferError('CREATION_UNCONFIRMED', 'Rental result unknown. Resolve the previous launch before renting')
    if instance and not record.get('ended_at'): history.destroyed(instance, label)
    if shutdown: return dict(launch=None)
    if not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', game_id):
        raise OfferError('GAME_UNKNOWN', 'Game identity is unknown. Choose a game on Home')
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'vastgame'
    games = library_summary(config/'games', desktop.STATE.parent/'selected_game')['games']
    game = next((game for game in games if game['id'] == game_id), None)
    if not game: raise OfferError('GAME_MISSING', 'Game is no longer in your library')
    return candidate(record, game, config/'games'/game_id/'manifest.json')


if __name__ == '__main__':
    try:
        if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != '--shutdown'): raise ValueError('Session ID required')
        print(json.dumps(dict(session=prepare(sys.argv[1], len(sys.argv) == 3))))
    except OfferError as exc:
        print(json.dumps(dict(error=exc.error)))
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps(dict(error=dict(code='SESSION_LOOKUP_FAILED', message='Cannot verify this session. Refresh to retry; no rig changed'))))
