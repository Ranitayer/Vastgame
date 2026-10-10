"""Freeze future launches and identify whether this guest ever attempted a game."""
import fcntl
import json
import re
from pathlib import Path
import sys


def freeze(label, gid='', root=Path('/var/lib/vast-gaming/status'), profiles=Path('/srv/gaming/profiles')):
    if not re.fullmatch(r'vastgame-[0-9]+', label):
        raise ValueError('Invalid shutdown identity')
    if (root/'instance-label').read_text().strip() != label:
        raise ValueError('Connected VM label differs')
    if (root/'game-id').exists():
        actual = (root/'game-id').read_text().strip()
    elif (root/'session.json').exists():
        actual = json.loads((root/'session.json').read_text()).get('game_id', '')
    else:
        actual = gid
    if not isinstance(actual, str) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', actual) or (gid and gid != actual):
        raise ValueError('Connected VM game identity is unavailable or differs')
    gid = actual
    # The new launch guard writes its activity marker before starting any child.
    # Older runtimes cannot prove that the game never ran.
    if not any((root/name).exists() for name in ('launch-guard-v1', 'bootstrap-launch-guard-v1')): return 'unknown'
    folder = profiles/gid
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'state.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        (root/'stopping').touch()
        return 'started' if (root/'game-started').exists() else 'unstarted'


if __name__ == '__main__':
    try: print(freeze(*sys.argv[1:]))
    except (OSError, ValueError): print('unknown')
