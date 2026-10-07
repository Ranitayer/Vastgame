#!/usr/bin/env python3
"""Link this checkout locally without touching accounts, manifests or VM state."""
import argparse
import os
from pathlib import Path
import shutil
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]


def install(home, config=None, data=None, state=None):
    home = Path(home)
    config = Path(config) if config else home/'.config'
    data = Path(data) if data else home/'.local/share'
    state = Path(state) if state else home/'.local/state'
    backup = None

    def preserve(path):
        nonlocal backup
        if backup is None:
            directory = state/'vastgame/installation-backups'
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            backup = Path(tempfile.mkdtemp(prefix='previous-', dir=directory))
        shutil.move(str(path), str(backup/path.name))

    native = data/'vastgame/native'
    old_client = config/'vastgame/client'
    # Native artifacts belong to this machine, not to source or configuration.
    if old_client.is_dir() and not old_client.is_symlink():
        native.mkdir(parents=True, exist_ok=True, mode=0o700)
        for relative in ('moonlight_hud.so', 'crashpad'):
            source = old_client/relative
            destination = native/relative
            if source.exists() and not destination.exists():
                if source.is_dir():
                    shutil.copytree(source, destination)
                else:
                    shutil.copy2(source, destination)

    targets = {
        home/'.local/bin/vastgame': ROOT/'bin/vastgame',
        config/'vastgame/runtime': ROOT/'src/runtime',
        config/'vastgame/client': ROOT/'src/client',
        config/'vastgame/vast-gaming-start-v2.sh': ROOT/'src/bootstrap/start.sh',
    }
    for destination, source in targets.items():
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() and destination.resolve() == source:
            continue
        if destination.exists() or destination.is_symlink():
            preserve(destination)
        temporary = destination.with_name('.'+destination.name+'.'+uuid.uuid4().hex)
        try:
            temporary.symlink_to(source)
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    print('Installed Vastgame from:', ROOT)
    if backup:
        print('Previous installation preserved in:', backup)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, default=Path.home())
    args = parser.parse_args()
    install(args.home,
            config=os.environ.get('XDG_CONFIG_HOME'),
            data=os.environ.get('XDG_DATA_HOME'),
            state=os.environ.get('XDG_STATE_HOME'))
