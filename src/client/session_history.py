"""Durable local session summaries and compressed, redacted engine logs."""
import argparse
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import fcntl
import gzip
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from failure_report import clean, redact
from startup_progress import STAGES

ROOT = Path(os.environ.get('XDG_STATE_HOME', Path.home()/'.local/state'))/'vastgame/sessions'
ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')


def milliseconds():
    return int(time.time() * 1000)


def new_label():
    """Reserve a rental identity atomically, including same-clock collisions."""
    if ROOT.is_symlink(): raise ValueError('Unsafe session directory')
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    ROOT.chmod(0o700)
    number = time.time_ns()
    while True:
        label = 'vastgame-'+str(number)
        try:
            (ROOT/label).mkdir(mode=0o700)
            return label
        except FileExistsError: number += 1


def folder(label):
    if not isinstance(label, str) or not re.fullmatch(r'vastgame-[0-9]{1,24}', label):
        raise ValueError('Invalid session identity')
    path = ROOT/label
    if ROOT.is_symlink() or path.is_symlink(): raise ValueError('Unsafe session directory')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    ROOT.chmod(0o700); path.chmod(0o700)
    return path


@contextmanager
def locked(label):
    path = folder(label)
    descriptor = os.open(path/'session.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield path


def write(path, record):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(clean(record), output, allow_nan=False, indent=2)
            output.write('\n'); output.flush(); os.fsync(output.fileno())
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def read(label):
    path = folder(label)/'session.json'
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as source:
        if os.fstat(source.fileno()).st_size > 1024*1024: raise ValueError('Session record is too large')
        record = json.load(source)
    if not isinstance(record, dict) or record.get('id') != label or record.get('schema') != 1: raise ValueError('Invalid session record')
    return record


def update(label, **changes):
    with locked(label) as path:
        record = read(label) if (path/'session.json').exists() else dict(
            schema=1, id=label, started_at=None, ended_at=None, instance_id=None,
            outcome='unknown', backup='unknown', rig={}, billing=dict(status='pending'))
        if record.get('history_deleted'):
            if record.get('outcome') == 'stopped': return record
            identity = {key: value for key, value in changes.items() if key in ('instance_id', 'job_id', 'outcome', 'force_shutdown')}
            if record.get('force_shutdown'):
                identity['force_shutdown'] = True
                if identity.get('outcome') != 'stopped': identity.pop('outcome', None)
            if identity.get('instance_id') and record.get('instance_id') not in (None, identity['instance_id']):
                raise ValueError('Session instance identity differs')
            record.update(identity); write(path/'session.json', record)
            return record
        if record.get('ended_at') or record.get('outcome') == 'stopped':
            changes = {key: value for key, value in changes.items() if key == 'billing'}
        elif record.get('force_shutdown'):
            if changes.get('outcome') != 'stopped' and changes.get('force_shutdown') is not True:
                for key in ('phase', 'progress_stage', 'outcome', 'game_running_at', 'game_running', 'backup'): changes.pop(key, None)
            if 'force_shutdown' in changes: changes['force_shutdown'] = True
        if changes.get('instance_id') and record.get('instance_id') not in (None, changes['instance_id']):
            raise ValueError('Session instance identity differs')
        running = changes.get('game_running')
        end = changes.get('ended_at')
        if end or running is False:
            since = record.get('game_active_since')
            if since:
                changes['game_duration_ms'] = record.get('game_duration_ms', 0) + max(0, (end or milliseconds())-since)
            changes['game_active_since'] = None
        elif running is True and not record.get('game_active_since'):
            changes['game_active_since'] = milliseconds()
        stages = dict(record.get('stage_times', {}))
        transitions = []
        for key in ('phase', 'progress_stage'):
            stage = changes.get(key)
            if isinstance(stage, str) and stage and stage != record.get(key):
                at = milliseconds()
                stages.setdefault(stage[:256], at)
                entry = dict(time=at, message=redact(stage))
                if entry not in transitions: transitions.append(entry)
        if stages != record.get('stage_times', {}): changes['stage_times'] = stages
        if transitions:
            try: append_stages(stage_archive(path, record), transitions)
            except (OSError, ValueError):
                changes.update(events_complete=False, events_error='Some stage transitions could not be archived; session identity is preserved.')
        record.update(clean(changes))
        record['updated_at'] = milliseconds()
        write(path/'session.json', record)
    bind_capture(label)
    return record


def bind_capture(label):
    capture = os.environ.get('VASTGAME_HISTORY_CAPTURE_FILE')
    if capture:
        path = Path(capture)
        if path.parent == ROOT and re.fullmatch(r'\.capture-[a-f0-9]{32}', path.name) and not path.is_symlink():
            write(path, dict(label=label))


def begin(label, game='', started_at=None, job=None):
    if game and not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', game): raise ValueError('Invalid game identity')
    if started_at is not None and (type(started_at) is not int or not 0 < started_at <= milliseconds()+60000):
        raise ValueError('Invalid session start time')
    fields = dict(game_id=game, outcome='preparing')
    if not (folder(label)/'session.json').exists(): fields.update(started_at=started_at or milliseconds(), logs_complete=True, events_complete=True, game_duration_ms=0)
    if job: fields['job_id'] = job
    config = Path(os.environ.get('XDG_CONFIG_HOME', Path.home()/'.config'))/'vastgame/games'
    if game:
        try:
            manifest = json.loads((config/game/'manifest.json').read_text())
            fields['game_name'] = str(manifest.get('name') or game)[:256]
        except (OSError, ValueError): fields['game_name'] = game
    return update(label, **fields)


def rig_snapshot(info):
    fields = ('machine_id', 'gpu_name', 'gpu_ram', 'num_gpus', 'cpu_name', 'cpu_cores',
              'cpu_ram', 'geolocation', 'disk_space', 'inet_down', 'inet_up', 'dph_total')
    return clean({key: info[key] for key in fields if key in info})


def append_stages(target, entries):
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'ab') as raw:
        os.fchmod(raw.fileno(), 0o600)
        with gzip.GzipFile(fileobj=raw, mode='wb', compresslevel=3) as output:
            for entry in entries:
                output.write((json.dumps(clean(entry), allow_nan=False)+'\n').encode())
        raw.flush(); os.fsync(raw.fileno())


def stage_archive(path, record):
    target = path/'stages.jsonl.gz'
    if target.is_symlink(): raise ValueError('Unsafe session stage archive')
    if not target.exists():
        # Older summaries contain only first observations; do not invent missing repeats.
        entries = [dict(time=at, message=redact(name)) for name, at in record.get('stage_times', {}).items()
                   if type(at) in (int, float) and math.isfinite(at) and at > 0]
        append_stages(target, sorted(entries, key=lambda item: item['time']))
    return target


def archive_rows(target, cursor, limit):
    if target.is_symlink(): raise ValueError('Unsafe session archive')
    if not target.exists(): return [], None
    entries, size = [], 0
    # Callers hold the writer lock, so a growing gzip member cannot appear partial.
    with gzip.open(target, 'rb') as source:
        if cursor:
            source.seek(cursor-1)
            if source.read(1) != b'\n': raise ValueError('Invalid archive cursor')
        while len(entries) < limit:
            position = source.tell()
            line = source.readline(1024*1024+1)
            if not line: break
            if len(line) > 1024*1024: raise ValueError('Session archive row exceeds the read limit')
            if entries and size+len(line) > 1024*1024:
                source.seek(position); break
            item = json.loads(line)
            if not isinstance(item, dict) or not isinstance(item.get('message'), str):
                raise ValueError('Invalid session archive row')
            at = item.get('time')
            if type(at) not in (int, float) or not math.isfinite(at) or not 0 < at < 8640000000000000:
                item['time'] = None
            entries.append(item); size += len(line)
        position = source.tell()
        more = bool(source.read(1))
    return entries, position if more else None


def log_page(label, cursor=0, limit=200, events=False):
    """Read complete archive rows with a bounded response and an opaque byte cursor."""
    if type(cursor) is not int or cursor < 0 or not 1 <= limit <= 200:
        raise ValueError('Invalid archive page')
    with locked(label) as path:
        record = read(label)
        if record.get('history_deleted'): raise ValueError('Session history was deleted')
        entries, next_cursor = archive_rows(stage_archive(path, record) if events else path/'logs.jsonl.gz', cursor, limit)
        result = dict(session=summary(record), entries=entries, next_cursor=next_cursor,
                      logs_complete=bool(record.get('logs_complete')), events_complete=bool(record.get('events_complete')))
        if record.get('events_error'): result['events_error'] = record['events_error']
        if not events and cursor == 0:
            try:
                result['events'], result['next_events_cursor'] = archive_rows(stage_archive(path, record), 0, limit)
            except (OSError, ValueError, EOFError):
                result.update(events=[], next_events_cursor=None, events_error='Stage history unavailable. Retry Events; raw logs remain available.')
        return result


def attach(info):
    label, instance = info.get('label'), str(info.get('id', ''))
    if not instance.isdecimal(): raise ValueError('Invalid instance identity')
    record = read(label) if (folder(label)/'session.json').exists() else {}
    fields = dict(instance_id=instance, rig=dict(record.get('rig', {}), **rig_snapshot(info)), outcome='active')
    provider_start = info.get('start_date')
    if type(provider_start) in (int, float) and math.isfinite(provider_start) and 0 < provider_start <= time.time()+60:
        fields['created_at'] = int(provider_start*1000)
        fields['rental_time_source'] = 'provider'
    elif record.get('creation_requested_at'):
        fields['created_at'] = record.get('created_at') or milliseconds()
        fields['rental_time_source'] = record.get('rental_time_source', 'creation_observed')
    rate = info.get('dph_total')
    if type(rate) in (int, float) and math.isfinite(rate) and rate >= 0: fields['hourly_price_usd'] = str(rate)
    if not record:
        fields.update(recovered=True, started_at=int(label[9:])//1000000 if len(label[9:]) >= 18 else None)
    return update(label, **fields)


def job_update(record):
    label = record.get('label')
    if not label: return
    if not (folder(label)/'session.json').exists(): begin(label, record.get('game', ''), record.get('started_at'), record.get('job'))
    previous = read(label)
    changes = dict(phase=record.get('phase', 'Preparing rig'), operation_pending=not record.get('finished') and not record.get('stopped'))
    progress = record.get('progress')
    if isinstance(progress, dict) and isinstance(progress.get('active'), str) and progress['active'] in dict(STAGES):
        changes['progress_stage'] = dict(STAGES)[progress['active']]
    if record.get('finished'): changes['last_attempt_success'] = bool(record.get('success'))
    if record.get('instance_id'): changes['instance_id'] = record['instance_id']
    if record.get('creation_requested'): changes['creation_requested_at'] = read(label).get('creation_requested_at') or milliseconds()
    if record.get('game_running'): changes['game_running_at'] = read(label).get('game_running_at') or milliseconds()
    if 'game_running' in record: changes['game_running'] = bool(record['game_running'])
    if record.get('force_shutdown'): changes.update(force_shutdown=True, backup='forced_skip')
    if record.get('stopped'): changes.update(outcome='stopped', ended_at=record.get('ended_at') or milliseconds())
    elif record.get('finished'):
        changes['outcome'] = 'active' if record.get('success') else 'retained' if record.get('instance_id') else 'unresolved'
        if not record.get('instance_id') and not record.get('creation_requested'):
            changes.update(outcome='no_rental', ended_at=milliseconds())
    update(label, **changes)
    if record.get('stopped') and previous.get('instance_id') and previous.get('outcome') != 'stopped': queue_refresh(label)


def backup_receipt(label, receipt):
    record = read(label)
    if receipt.get('schema') != 1 or receipt.get('instance_id') != record.get('instance_id') or not isinstance(receipt.get('snapshot'), str) or not receipt['snapshot']:
        raise ValueError('Backup receipt differs from this session')
    update(label, backup='verified', backup_snapshot=receipt['snapshot'], backup_verified_at=milliseconds())


class LogWriter:
    def __init__(self, label, phase=None):
        self.label, self.phase, self.secret = label, phase, False

    def append(self, raw, at=None):
        line = ANSI.sub('', raw).rstrip()
        if '-----BEGIN ' in line and 'PRIVATE KEY-----' in line:
            self.secret = True; line = '[private key redacted]'
        elif self.secret:
            if '-----END ' in line and 'PRIVATE KEY-----' in line: self.secret = False
            return
        if not line.strip(): return
        line = redact(line).replace(str(Path.home()), '~')
        with locked(self.label) as path:
            if (path/'session.json').exists() and read(self.label).get('history_deleted'): return
            target = path/'logs.jsonl.gz'
            with gzip.open(target, 'at', encoding='utf-8', compresslevel=3) as output:
                output.write(json.dumps(dict(time=at if type(at) in (int, float) and at > 0 else milliseconds(), message=line), allow_nan=False)+'\n')
            target.chmod(0o600)
        changes = {}
        if self.phase:
            stage = self.phase(line)
            if stage and stage != read(self.label).get('phase'): changes['phase'] = stage
            if stage == 'Game running':
                changes['game_running'] = True
                if not read(self.label).get('game_running_at'): changes['game_running_at'] = milliseconds()
        if '✓ Game closed and Wine state flushed' in line: changes['game_running'] = False
        if 'Final Google Drive state backup complete' in line: changes['backup'] = 'verified'
        elif 'Game never started; skipping backup' in line: changes['backup'] = 'not_needed'
        elif 'Final backup could not be confirmed' in line: changes['backup'] = 'failed'
        elif 'Force shutdown requested:' in line: changes.update(backup='forced_skip', force_shutdown=True)
        if line.lstrip().startswith(('ERROR:', '[VASTGAME_ERROR]')): changes['last_error'] = line[:4096]
        if changes: update(self.label, **changes)


def finish_attempt(label, code):
    record = read(label)
    if record.get('ended_at'): return
    if record.get('instance_id'):
        update(label, outcome='active' if code == 0 else 'retained', operation_pending=False, last_attempt_success=code == 0)
    elif record.get('creation_requested_at'):
        update(label, outcome='unresolved', operation_pending=False, last_attempt_success=False)
    else:
        update(label, outcome='no_rental', ended_at=milliseconds())


def queue_refresh(label):
    if read(label).get('history_deleted'): return
    # Billing is a bounded one-shot worker, independent of paid lifecycle locks.
    subprocess.Popen([sys.executable, str(Path(__file__)), 'refresh', label],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     close_fds=True, start_new_session=True,
                     env={key: value for key, value in os.environ.items() if key != 'VASTGAME_HISTORY_CAPTURE_FILE'})


def destroyed(instance, label=None):
    records = [read(label)] if label else []
    if not label:
        for path in ROOT.glob('vastgame-*/session.json'):
            try: records.append(read(path.parent.name))
            except (OSError, ValueError): continue
    for record in records:
        if record.get('instance_id') == instance:
            if record.get('outcome') == 'stopped': continue
            update(record['id'], outcome='stopped', ended_at=record.get('ended_at') or milliseconds(), phase='Rig shut down')
            queue_refresh(record['id'])


def archive_job(path):
    """Import retained legacy diagnostics once, before their disposable job is pruned."""
    if path.stat().st_size > 1024*1024: raise ValueError('Job record is too large')
    record = json.loads(path.read_text())
    if not isinstance(record, dict): raise ValueError('Invalid legacy job record')
    label = record.get('label')
    if not isinstance(label, str) or not re.fullmatch(r'vastgame-[0-9]{1,24}', label): return
    target = folder(label)
    if (target/'session.json').exists(): return
    # Keep an import unpublished until all retained logs have been archived.
    with locked(label):
        if (target/'session.json').exists(): return
        logs = target/'logs.jsonl.gz'
        logs.unlink(missing_ok=True)
        secret = False
        with gzip.open(logs, 'wt', encoding='utf-8', compresslevel=3) as output:
            for name in ('previous.jsonl', 'events.jsonl'):
                source = path.parent/name
                if not source.is_file() or source.is_symlink(): continue
                with source.open() as incoming:
                    for line in incoming:
                        if len(line) > 16384: continue
                        event = json.loads(line)
                        text = event.get('line')
                        if event.get('type') != 'log' or not isinstance(text, str): continue
                        if '-----BEGIN ' in text and 'PRIVATE KEY-----' in text:
                            secret = True; text = '[private key redacted]'
                        elif secret:
                            if '-----END ' in text and 'PRIVATE KEY-----' in text: secret = False
                            continue
                        output.write(json.dumps(dict(time=event.get('time'), message=redact(text)))+'\n')
        logs.chmod(0o600)
        imported = dict(schema=1, id=label, job_id=record.get('job'), game_id=record.get('game', ''),
                        started_at=record.get('started_at') or (int(label[9:])//1000000 if len(label[9:]) >= 18 else None),
                        ended_at=record.get('ended_at'), instance_id=record.get('instance_id'),
                        outcome='stopped' if record.get('stopped') else 'retained' if record.get('instance_id') else 'unresolved',
                        phase=record.get('phase'), rig={}, backup='unknown', billing=dict(status='pending'),
                        recovered=True, logs_complete=False, updated_at=milliseconds())
        write(target/'session.json', imported)


def summary(record):
    result = dict(record)
    result['summary_at'] = milliseconds()
    # Existing workers may predate the pending-operation field; their exact local job is authoritative.
    job = record.get('job_id')
    if isinstance(job, str) and re.fullmatch(r'[a-f0-9]{32}', job) and not record.get('ended_at'):
        path = ROOT.parent/'desktop'/job/'job.json'
        try:
            if not path.parent.is_symlink() and not path.is_symlink() and path.stat().st_size <= 1024*1024:
                current = json.loads(path.read_text())
                if current.get('job') == job and current.get('label') == record['id']:
                    result['operation_pending'] = not current.get('finished') and not current.get('stopped')
                    if current.get('finished'): result['last_attempt_success'] = bool(current.get('success'))
        except (OSError, ValueError, AttributeError): pass
    now = record.get('ended_at') or (None if record.get('outcome') == 'stopped' else milliseconds())
    start = record.get('started_at')
    result['duration_ms'] = max(0, now-start) if start and now else None
    played = record.get('game_duration_ms')
    since = record.get('game_active_since')
    result['played_ms'] = (played or 0) + max(0, now-since) if since and now else played
    created, rate = record.get('created_at'), record.get('hourly_price_usd')
    try:
        estimate = Decimal(str(rate)) * Decimal(max(0, now-created)) / Decimal(3600000) if created and now and rate is not None else None
        result['estimated_compute_storage_usd'] = str(estimate.quantize(Decimal('0.000001'))) if estimate is not None and estimate.is_finite() else None
    except (InvalidOperation, TypeError): result['estimated_compute_storage_usd'] = None
    result['state'] = display_state(result)
    return result


def display_state(record):
    if record.get('ended_at') or record.get('outcome') == 'stopped':
        return 'Failed' if record.get('outcome') == 'no_rental' else 'Shutdown'
    if record.get('operation_pending') or record.get('outcome') in ('preparing', 'creating'): return 'Starting'
    if record.get('phase') == 'Game exited': return 'Retained'
    if record.get('phase') == 'Game running' and record.get('game_running'): return 'Running'
    if record.get('last_attempt_success') is False: return 'Failed'
    if record.get('outcome') == 'retained': return 'Retained'
    if record.get('outcome') == 'active': return 'Retained' if record.get('game_running') is False else 'Running'
    return 'Failed'


def select_sessions(records, days=0, state='All', order='newest'):
    since = milliseconds()-days*86400000 if days else 0
    items = [summary(record) for record in records if not since or (record.get('started_at') or 0) >= since]
    if state != 'All': items = [item for item in items if item['state'] == state]
    def value(item):
        if order in ('highest-cost', 'lowest-cost'):
            raw = item.get('billing', {}).get('reported_usd')
            if raw is None: raw = item.get('estimated_compute_storage_usd')
            try:
                amount = Decimal(str(raw))
                return amount if amount.is_finite() else None
            except InvalidOperation: return None
        return item.get('played_ms')
    def key(item):
        newest = (-(item.get('started_at') or 0), item['id'])
        if order in ('newest', 'oldest'):
            return ((item.get('started_at') or 0) if order == 'oldest' else newest[0], item['id'])
        amount = value(item)
        return (amount is None, (-amount if order in ('highest-cost', 'longest-time') else amount) if amount is not None else 0, *newest)
    return sorted(items, key=key)


def visible_session(record):
    if record.get('history_deleted'): return False
    closed = bool(record.get('ended_at')) or record.get('outcome') in ('stopped', 'no_rental')
    details = (record.get('instance_id') or record.get('rig') or record.get('hourly_price_usd') is not None or
               record.get('played_ms') is not None or record.get('game_duration_ms') is not None or
               record.get('billing', {}).get('reported_usd') is not None)
    return not (record.get('recovered') and closed and not details)


def reconcile_billing(record, charges, error=None):
    from charges import session_charges
    try:
        if error is not None: raise ValueError(error or 'Billing request failed')
        billing = session_charges(charges, record['instance_id'], record['id'])
        billing['observed_at'] = milliseconds()
        if billing['status'] == 'pending' and record.get('billing', {}).get('reported_usd') is not None:
            billing = dict(record['billing'], status='stale', error=billing['error'], attempted_at=milliseconds())
    except (OSError, ValueError) as exc:
        billing = dict(record.get('billing', {}), status='stale' if record.get('billing', {}).get('reported_usd') is not None else 'pending', error=str(exc), attempted_at=milliseconds())
    update(record['id'], billing=billing)


def refresh(label):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'providers/vast'))
    from charges import fetch_charges
    with (folder(label)/'billing.lock').open('a') as lock:
        os.chmod(lock.name, 0o600)
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return read(label)
        record = read(label)
        if record.get('history_deleted') or not record.get('instance_id'): return record
        if not isinstance(record['instance_id'], str) or not record['instance_id'].isdecimal():
            update(label, billing=dict(status='unavailable', error='Exact session instance identity is unknown'))
            return read(label)
        start = record.get('created_at') or record.get('started_at')
        if not start:
            update(label, billing=dict(status='unavailable', error='Session start time is unknown'))
            return read(label)
        charges, error = None, None
        try: charges = fetch_charges(start//1000, milliseconds()//1000)
        except (OSError, ValueError) as exc: error = str(exc)
        reconcile_billing(read(label), charges, error)
        return read(label)


def refresh_page(records):
    """Reconcile one displayed page against a single bounded charge lookup."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'providers/vast'))
    from charges import fetch_charges
    eligible = [record for record in records if isinstance(record.get('instance_id'), str) and
                record['instance_id'].isdecimal() and (record.get('created_at') or record.get('started_at'))]
    if not eligible: return records
    charges, error = None, None
    try: charges = fetch_charges(min(record.get('created_at') or record['started_at'] for record in eligible)//1000, milliseconds()//1000)
    except (OSError, ValueError) as exc: error = str(exc)
    for record in eligible:
        with (folder(record['id'])/'billing.lock').open('a') as lock:
            os.chmod(lock.name, 0o600)
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: continue
            reconcile_billing(read(record['id']), charges, error)
    return [read(record['id']) for record in records]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('list', 'show', 'logs', 'log-page', 'event-page', 'refresh', 'begin', 'offer', 'attach', 'requested', 'destroyed', 'state', 'receipt'))
    parser.add_argument('id', nargs='?')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--cursor', type=int, default=0)
    parser.add_argument('--refresh-billing', action='store_true')
    parser.add_argument('--days', type=int, choices=(0, 1, 3, 7, 30, 365), default=0)
    parser.add_argument('--status', choices=('All', 'Starting', 'Running', 'Failed', 'Retained', 'Shutdown'), default='All')
    parser.add_argument('--sort', choices=('newest', 'oldest', 'highest-cost', 'lowest-cost', 'longest-time', 'shortest-time'), default='newest')
    args = parser.parse_args()
    if not 1 <= args.limit <= 200 or args.offset < 0: parser.error('Invalid page size or offset')
    try:
        if args.action == 'begin':
            data = json.load(sys.stdin); begin(args.id, data.get('game', ''), data.get('started_at'), data.get('job'))
        elif args.action == 'offer':
            data = json.load(sys.stdin)
            update(args.id, rig=rig_snapshot(data['offer']), hourly_price_usd=str(data['offer']['dph_total']), allocated_disk_gb=data['disk_gb'])
        elif args.action == 'attach': attach(json.load(sys.stdin))
        elif args.action == 'receipt': backup_receipt(args.id, json.load(sys.stdin))
        elif args.action == 'requested': update(args.id, creation_requested_at=milliseconds(), outcome='creating')
        elif args.action == 'state':
            data = json.load(sys.stdin)
            if set(data)-{'backup', 'force_shutdown'} or data.get('backup') not in ('not_needed', 'verified', 'failed', 'forced_skip'):
                raise ValueError('Invalid session state')
            if 'force_shutdown' in data and type(data['force_shutdown']) is not bool: raise ValueError('Invalid shutdown state')
            update(args.id, **data)
        elif args.action == 'destroyed': destroyed(args.id)
        elif args.action in ('log-page', 'event-page'):
            print(json.dumps(log_page(args.id, args.cursor, args.limit, args.action == 'event-page'), allow_nan=False))
        elif args.action == 'logs':
            with gzip.open(folder(args.id)/'logs.jsonl.gz', 'rt', encoding='utf-8') as source:
                for line in source:
                    if args.json: print(line, end='')
                    else: print(json.loads(line)['message'])
        elif args.action in ('show', 'refresh'):
            if not args.id: parser.error('Session ID required')
            record = refresh(args.id) if args.action == 'refresh' else read(args.id)
            print(json.dumps(dict(session=summary(record)), allow_nan=False, indent=None if args.json else 2))
        else:
            records, unreadable = [], 0
            for job in ROOT.parent.glob('desktop/*/job.json'):
                if job.parent.is_symlink() or not re.fullmatch(r'[a-f0-9]{32}', job.parent.name): continue
                try: archive_job(job)
                except (OSError, ValueError, TypeError): unreadable += 1
            for path in ROOT.glob('vastgame-*/session.json'):
                try:
                    record = read(path.parent.name)
                    if visible_session(record): records.append(record)
                except (OSError, ValueError): unreadable += 1
            source = records
            records = select_sessions(source, args.days, args.status, args.sort)
            page = records[args.offset:args.offset+args.limit]
            if args.refresh_billing:
                refresh_page(page)
                records = select_sessions([read(item['id']) for item in source], args.days, args.status, args.sort)
                page = records[args.offset:args.offset+args.limit]
            print(json.dumps(dict(sessions=page,
                                  total=len(records), skipped=unreadable), allow_nan=False, indent=None if args.json else 2))
        return 0
    except (OSError, ValueError, TypeError, KeyError):
        print('Session history unavailable; check the session ID, local storage and account access', file=sys.stderr)
        return 1


if __name__ == '__main__': sys.exit(main())
