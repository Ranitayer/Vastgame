#!/usr/bin/env python3
"""Reuse native Moonlight identity/settings in the installed Flatpak client."""
import configparser
import os
from pathlib import Path
import subprocess
import tempfile


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def identity(data):
    settings = configparser.ConfigParser(interpolation=None)
    settings.read_string(data.decode())
    return tuple(settings.get('General', key, fallback='') for key in ('certificate', 'key', 'uniqueid'))


def migrate(source, destination):
    if not source.is_file():
        return False
    data = source.read_bytes()
    native_identity = identity(data)
    if not all(native_identity):
        raise ValueError('Native Moonlight pairing identity is incomplete')
    if destination.is_file():
        previous = destination.read_bytes()
        if identity(previous) == native_identity:
            return False
        backup = destination.with_name('Moonlight.conf.before-vastgame')
        if not backup.exists():
            atomic_write(backup, previous)
    # Preserve Qt's INI encoding exactly, including serialized certificates.
    atomic_write(destination, data)
    return True


if __name__ == '__main__':
    if subprocess.run(['pgrep', '-x', 'moonlight'], stdout=subprocess.DEVNULL).returncode == 0:
        raise SystemExit('Close Moonlight before importing its existing pairing settings; VM is unaffected.')
    home = Path.home()
    source = Path(os.environ.get('XDG_CONFIG_HOME', str(home/'.config')))/'Moonlight Game Streaming Project/Moonlight.conf'
    destination = home/'.var/app/com.moonlight_stream.Moonlight/config/Moonlight Game Streaming Project/Moonlight.conf'
    if migrate(source, destination):
        print('Existing Moonlight pairing and settings imported into Flatpak; previous settings backed up locally.')
