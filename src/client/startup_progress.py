"""Public whole-stage startup measurements; never invent an overall ETA."""
import json
import math
import sys
import time

STAGES = [('boot', 'Booting rig'), ('game', 'Restoring game'), ('runtime', 'Preparing runtime'),
          ('saves', 'Restoring saves'), ('start', 'Starting game')]


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def empty():
    return dict(active='boot', stages=[dict(id=key, name=name, state='pending') for key, name in STAGES])


def from_tasks(payload, now=None):
    tasks = payload.get('tasks', {})
    if not isinstance(tasks, dict): raise ValueError('Invalid startup tasks')
    now = time.time() if now is None else now
    result = empty()
    items = {item['id']: item for item in result['stages']}
    items['boot']['state'] = 'done'  # Progress is fetched only from a verified online guest.
    for key, task_key in [('game', 'game'), ('saves', 'state')]:
        task = tasks.get(task_key, {})
        if not isinstance(task, dict): continue
        item = items[key]
        item['state'] = task.get('state') if task.get('state') in ('pending', 'running', 'done', 'error') else 'pending'
        done, total = number(task.get('bytes')), number(task.get('total'))
        if total and done is not None:
            item.update(bytes=min(done, total), total=total, percent=min(100, int(done / total * 100)))
            speed, updated = number(task.get('speed')), number(task.get('updated'))
            if item['state'] == 'running' and done < total and speed and updated and -2 <= now - updated <= 10:
                item.update(speed=speed, eta=(total - done) / speed, measured_at=updated)
            if done >= total and item['state'] != 'done': item['action'] = 'Transfer complete; finalizing'
    runtime = [tasks.get(key, {}).get('state', 'pending') for key in ('core', 'images', 'identity', 'proton', 'dx12', 'prefix', 'setup')]
    items['runtime']['state'] = 'error' if 'error' in runtime else 'done' if all(state == 'done' for state in runtime) else 'running' if 'running' in runtime else 'pending'
    ready = tasks.get('phase', {}).get('action') == 'READY'
    if ready:
        for key in ('game', 'runtime', 'saves'): items[key]['state'] = 'done'
        items['start']['state'] = 'running'
    result['active'] = next((key for key in ('game', 'saves', 'runtime', 'start') if items[key]['state'] == 'error'), None) or \
        next((key for key in ('game', 'saves', 'runtime', 'start') if items[key]['state'] == 'running'), 'runtime')
    return result


def milestone(previous, phase):
    result = previous or empty()
    items = {item['id']: item for item in result['stages']}
    if phase in ('Creating rig', 'Allocating host', 'Preparing image', 'Booting rig', 'Connecting Tailscale'):
        result['active'] = 'boot'; items['boot'].update(state='running', action=phase)
    elif phase == 'Preparing runtime':
        items['boot']['state'] = 'done'; result['active'] = 'runtime'; items['runtime']['state'] = 'running'
    elif phase in ('Starting game', 'Starting Moonlight', 'Game running'):
        for key in ('boot', 'game', 'runtime', 'saves'): items[key]['state'] = 'done'
        result['active'] = 'start'; items['start']['state'] = 'done' if phase == 'Game running' else 'running'
    return result


if __name__ == '__main__':
    try: print(json.dumps(from_tasks(json.load(sys.stdin))))
    except (ValueError, TypeError, AttributeError): sys.exit(1)
