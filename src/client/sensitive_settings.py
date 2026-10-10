"""Explicitly confirmed settings actions; never triggered by browsing or startup."""
from collections import Counter
from contextlib import contextmanager
import fcntl
import json
import os
import re
import subprocess
import sys
import time
import desktop_launch as desktop
import session_history as history

LABEL = re.compile(r'vastgame-[0-9]{1,24}')


def jobs():
    result = []
    for path in desktop.STATE.glob('*/job.json'):
        if path.is_symlink() or path.parent.is_symlink() or not re.fullmatch(r'[a-f0-9]{32}', path.parent.name): continue
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(descriptor) as source:
                if os.fstat(source.fileno()).st_size > 1024*1024: continue
                record = json.load(source)
        except (OSError, ValueError): continue
        if isinstance(record, dict) and record.get('job') == path.parent.name and LABEL.fullmatch(str(record.get('label', ''))): result.append(record)
    return result


@contextmanager
def action_lock(name, wait=0):
    path = history.ROOT.parent/name
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'a') as lock:
        deadline = time.monotonic()+wait
        while True:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); break
            except BlockingIOError:
                if time.monotonic() >= deadline: raise ValueError('Another operation is still active; retry after it finishes')
                time.sleep(0.1)
        yield


def delete_history():
    if history.ROOT.is_symlink(): raise ValueError('Unsafe session directory')
    labels = {path.name for path in history.ROOT.glob('vastgame-*') if LABEL.fullmatch(path.name)}
    labels.update(record['label'] for record in jobs())
    deleted, failed = 0, []
    for label in sorted(labels):
        try:
            with history.locked(label) as path:
                try: record = history.read(label)
                except (FileNotFoundError, ValueError): record = {}
                # Tombstones stop workers and legacy imports recreating erased history.
                tombstone = dict(schema=1, id=label, history_deleted=True)
                if record.get('ended_at') or record.get('outcome') in ('stopped', 'no_rental'): tombstone['outcome'] = 'stopped'
                if not record.get('ended_at') and record.get('outcome') not in ('stopped', 'no_rental'):
                    for key in ('instance_id', 'job_id', 'outcome', 'force_shutdown'):
                        if key in record: tombstone[key] = record[key]
                history.write(path/'session.json', tombstone)
                for name in ('logs.jsonl.gz', 'stages.jsonl.gz'): (path/name).unlink(missing_ok=True)
                deleted += 1
        except (OSError, ValueError) as exc: failed.append(dict(id=label, message=str(exc)))
    return dict(ok=not failed, deleted=deleted, failed=failed)


def targets(rows):
    pairs = []
    for row in rows:
        if not isinstance(row, dict) or not LABEL.fullmatch(str(row.get('label', ''))): continue
        instance = str(row.get('id', ''))
        if not re.fullmatch(r'[0-9]{1,24}', instance) or int(instance) <= 0: raise ValueError('Provider returned an invalid Vastgame instance identity')
        pairs.append((instance, row['label']))
    if any(count != 1 for count in Counter(instance for instance, _ in pairs).values()) or any(count != 1 for count in Counter(label for _, label in pairs).values()):
        raise ValueError('Provider returned ambiguous Vastgame identities; no destruction submitted')
    return pairs


def stop_instance(instance, label):
    child = subprocess.Popen([str(desktop.BIN), 'stop', '--force', '--instance-id', instance, '--label', label],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             env=dict(os.environ, VASTGAME_DESKTOP='1', VASTAI_NO_UPDATE_CHECK='1'))
    for raw in iter(lambda: child.stdout.readline(16384), b''):
        desktop.emit('log', line=history.redact(raw.decode(errors='replace').rstrip()))
    return child.wait() == 0


def force_stop_all():
    known = jobs()
    for index, record in enumerate(known):
        if record.get('stopped') or (record.get('finished') and not record.get('instance_id')): continue
        record = desktop.update_job(desktop.STATE/record['job'], force_shutdown=True, shutdown_requested=True, phase='Shutting down rig')
        known[index] = record
        desktop.interrupt_worker(record, record['job'], 'stop_', 'stop')
        desktop.interrupt_worker(record, record['job'])
        desktop.interrupt_worker(record, record['job'], mode='connect')
    # Cancel owned workers, then block replacement rentals until the snapshot is handled.
    with action_lock('lifecycle.lock', wait=90):
        # Output drained after cancellation can still identify an already-submitted rental.
        known = jobs()
        chosen = targets(desktop.instance_rows())
        confirmed, failed = [], []
        for instance, label in chosen:
            desktop.emit('status', phase=f'Force stopping instance {instance}')
            try:
                if not stop_instance(instance, label): raise ValueError('Provider destruction was not confirmed; rig may still be billing')
                confirmed.append(instance)
                for record in known:
                    if record['label'] == label and record.get('instance_id') in (None, instance):
                        desktop.update_job(desktop.STATE/record['job'], stopped=True, finished=True, success=True, instance_id=None, game_running=False, phase='Rig shut down')
            except (OSError, ValueError) as exc: failed.append(dict(id=instance, message=str(exc)))
        for record in known:
            if not record.get('stopped') and record.get('creation_requested') and not record.get('instance_id') and not any(label == record['label'] for _, label in chosen):
                failed.append(dict(id=record['label'], message='Creation result remains unknown; retry after refreshing provider status'))
        return dict(ok=not failed, confirmed=confirmed, failed=failed)


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) == 2 else ''
    try:
        if action not in ('force-stop', 'delete-history'): raise ValueError('Invalid sensitive action')
        with action_lock('sensitive-settings.lock'):
            result = force_stop_all() if action == 'force-stop' else delete_history()
        desktop.emit('finished', action=action, result=result, ok=result['ok'])
    except (OSError, ValueError, TypeError) as exc:
        desktop.emit('finished', action=action, ok=False, result=dict(ok=False, failed=[dict(message=str(exc))]))
