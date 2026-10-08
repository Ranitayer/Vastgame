#!/usr/bin/env python3
# Add the direct Moonlight app while preserving Wolf pairing.
import copy
import json
from pathlib import Path
import re
import sys
try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        try:
            from pip._vendor import tomli as tomllib
        except ModuleNotFoundError as exc:
            raise RuntimeError('No TOML parser available; install python3-tomli for Python 3.10') from exc
import uuid
from game_session import validate


def configure(text, m):
    validate(m)
    d = tomllib.loads(text)
    gid = m['id']
    profiles = d.get('profiles', [])
    sources = [a for p in profiles for a in p.get('apps', [])
               if a.get('runner', {}).get('image', '').startswith('ghcr.io/games-on-whales/lutris:')]
    if not sources:
        raise ValueError('Wolf config contains no Lutris Docker app to clone')
    if sum(p.get('id') == 'moonlight-profile-id' for p in profiles) != 1:
        raise ValueError('Expected exactly one Moonlight profile')
    runner = copy.deepcopy(sources[0]['runner'])
    runner['name'] = 'WolfLutris_vastgame_' + gid
    # Preparation and gameplay must use the same installed MangoHud layer.
    runner['image'] = 'vastgame-preparation:v1'
    mounts = {
        '/var/lutris/': f'/srv/gaming/lutris/{gid}:/var/lutris/:rw',
        # Wolf always injects /home/retro itself. Share its top-level runtime
        # directories without adding a conflicting second HOME mount.
        '/home/retro/.local': f'/srv/gaming/lutris/{gid}/home/.local:/home/retro/.local:rw',
        '/home/retro/.config': f'/srv/gaming/lutris/{gid}/home/.config:/home/retro/.config:rw',
        '/home/retro/.cache': f'/srv/gaming/lutris/{gid}/home/.cache:/home/retro/.cache:rw',
        '/games': '/srv/gaming/games:/games:rw',
        '/profiles': '/srv/gaming/profiles:/profiles:rw',
        '/prefixes': '/srv/gaming/prefixes:/prefixes:rw',
        '/saves': '/srv/gaming/saves:/saves:rw',
        '/configs': '/srv/gaming/configs:/configs:rw',
        '/shaders': '/srv/gaming/shaders:/shaders:rw',
        '/opt/vastgame': '/opt/vastgame:/opt/vastgame:ro',
        '/opt/gow/startup.d/90-vastgame.sh': '/opt/vastgame/90-vastgame.sh:/opt/gow/startup.d/90-vastgame.sh:ro',
        '/vastgame-status': '/var/lib/vast-gaming/status:/vastgame-status:rw',
    }
    destinations = {k.rstrip('/') for k in mounts} | {'/home/retro'}
    runner['mounts'] = [s for s in runner.get('mounts', []) if s.split(':')[1].rstrip('/') not in destinations] + list(mounts.values())
    env = dict(s.split('=', 1) for s in runner.get('env', []) if '=' in s)
    devices = env.get('GOW_REQUIRED_DEVICES', '/dev/dri/* /dev/nvidia* /var/lutris/').split()
    if '/dev/input/event*' not in devices:
        devices.insert(0, '/dev/input/event*')
    env['GOW_REQUIRED_DEVICES'] = ' '.join(devices)
    env.update(WOLF_LUTRIS_GAMEPAD_UI_ENABLE='0', RUN_SWAY='', RUN_GAMESCOPE='1', GAMESCOPE_MODE='-f')
    runner['env'] = [k + '=' + v for k, v in env.items()]
    # Wolf derives a Docker volume name from the advertised app title. Keep the
    # title free of ':' and other Docker name separators.
    title = 'Vastgame - ' + gid
    # Serialize only the new flat runner table. JSON strings/arrays are valid TOML values.
    block = '\n# BEGIN VASTGAME DIRECT APP\n[[profiles.apps]]\n'
    block += 'title = ' + json.dumps(title) + '\nstart_virtual_compositor = true\n'
    block += '[profiles.apps.runner]\n'
    for k, v in runner.items():
        if not isinstance(v, (str, list)):
            raise ValueError('Unsupported Wolf runner field: ' + k)
        block += k + ' = ' + json.dumps(v) + '\n'
    block += '# END VASTGAME DIRECT APP\n'
    text = re.sub(r'\n# BEGIN VASTGAME DIRECT APP\n.*?# END VASTGAME DIRECT APP\n', '', text, flags=re.S)
    starts = list(re.finditer(r'^\s*\[\[profiles\]\]\s*$', text, re.M))
    index = next(i for i, p in enumerate(profiles) if p['id'] == 'moonlight-profile-id')
    end = starts[index + 1].start() if index + 1 < len(starts) else len(text)
    result = text[:end] + block + '\n' + text[end:]
    parsed = tomllib.loads(result)
    if parsed.get('paired_clients') != d.get('paired_clients') or parsed.get('uuid') != d.get('uuid'):
        raise ValueError('Pairing changed unexpectedly')
    return result, title


if __name__ == '__main__':
    cfg, manifest, status = map(Path, sys.argv[1:])
    m = json.loads(manifest.read_text())
    result, title = configure(cfg.read_text(), m)
    tmp = cfg.with_suffix('.tmp')
    tmp.write_text(result)
    tmp.replace(cfg)
    status.mkdir(parents=True, exist_ok=True)
    session = dict(game_id=m['id'], app_title=title, session_id=uuid.uuid4().hex)
    (status / 'session.json').write_text(json.dumps(session))
    (status / 'launch.json').write_text(json.dumps(dict(session, state='pending', action='Waiting for Moonlight connection')))
