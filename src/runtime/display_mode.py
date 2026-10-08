"""Resize an existing game's Gamescope display without replacing its runtime."""
import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


def identity(root, label, game, session):
    record = json.loads((root/'session.json').read_text())
    if ((root/'instance-label').read_text().strip() != label
            or record.get('game_id') != game or record.get('session_id') != session):
        raise ValueError('VM or game session changed; display left unchanged')


def resize(width, height, label, game, session):
    identity(Path('/vastgame-status'), label, game, session)
    for process in Path('/proc').glob('[0-9]*'):
        try:
            if b'/opt/vastgame/game_session.py' not in (process/'cmdline').read_bytes().split(b'\0'):
                continue
            environment = dict(entry.split(b'=', 1) for entry in (process/'environ').read_bytes().split(b'\0') if b'=' in entry)
            if b'DISPLAY' not in environment: continue
            for key in (b'DISPLAY', b'XAUTHORITY', b'HOME', b'XDG_RUNTIME_DIR'):
                if key in environment: os.environ[key.decode()] = os.fsdecode(environment[key])
                else: os.environ.pop(key.decode(), None)
            # Xwayland authenticates local connections as the game user, not Docker's root user.
            owner = process.stat()
            if os.geteuid() == 0:
                os.setgroups([])
                os.setgid(owner.st_gid)
                os.setuid(owner.st_uid)
            elif os.geteuid() != owner.st_uid:
                raise ValueError('Display helper must run as the game user')
            break
        except OSError:
            continue
    else:
        raise ValueError('Game display is not ready; reconnect after game startup')
    library = ctypes.util.find_library('X11')
    if not library: raise ValueError('X11 display library is unavailable')
    x11 = ctypes.CDLL(library)
    pointer, number = ctypes.c_void_p, ctypes.c_ulong
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]; x11.XOpenDisplay.restype = pointer
    x11.XDefaultRootWindow.argtypes = [pointer]; x11.XDefaultRootWindow.restype = number
    x11.XInternAtom.argtypes = [pointer, ctypes.c_char_p, ctypes.c_int]; x11.XInternAtom.restype = number
    x11.XChangeProperty.argtypes = [pointer, number, number, number, ctypes.c_int, ctypes.c_int,
                                   ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int]
    x11.XSync.argtypes = [pointer, ctypes.c_int]
    x11.XCloseDisplay.argtypes = [pointer]
    x11.XGetGeometry.argtypes = [pointer, number, ctypes.POINTER(number), ctypes.POINTER(ctypes.c_int),
                                ctypes.POINTER(ctypes.c_int), *[ctypes.POINTER(ctypes.c_uint)]*4]
    display = x11.XOpenDisplay(os.fsencode(os.environ['DISPLAY']))
    if not display: raise ValueError('Cannot open the active game display')
    try:
        root = x11.XDefaultRootWindow(display)
        def current_size():
            parent = number(); x = ctypes.c_int(); y = ctypes.c_int()
            actual_w = ctypes.c_uint(); actual_h = ctypes.c_uint(); border = ctypes.c_uint(); depth = ctypes.c_uint()
            if x11.XGetGeometry(display, root, ctypes.byref(parent), ctypes.byref(x), ctypes.byref(y),
                                ctypes.byref(actual_w), ctypes.byref(actual_h), ctypes.byref(border), ctypes.byref(depth)):
                return actual_w.value, actual_h.value
        if current_size() == (width, height): return
        control = x11.XInternAtom(display, b'GAMESCOPE_XWAYLAND_MODE_CONTROL', 1)
        if not control:
            raise ValueError('Gamescope does not support live resizing; restart the game at the selected resolution')
        # Xlib stores format-32 property elements in native unsigned longs.
        values = (number*4)(0, width, height, 1)
        x11.XChangeProperty(display, root, control, x11.XInternAtom(display, b'CARDINAL', 0),
                            32, 0, ctypes.cast(values, ctypes.POINTER(ctypes.c_ubyte)), 4)
        for _ in range(30):
            x11.XSync(display, 0)
            if current_size() == (width, height):
                print(f'Game display: {width}x{height}; resolution available to the game', flush=True)
                return
            time.sleep(0.1)
        raise ValueError('Game display did not accept the requested resolution; a game restart may be needed')
    finally:
        x11.XCloseDisplay(display)


def host(label, game, session, width, height):
    identity(Path('/var/lib/vast-gaming/status'), label, game, session)
    rows = subprocess.check_output(['docker', 'ps', '--format', '{{.ID}} {{.Names}}'], text=True, timeout=5)
    containers = [row.split()[0] for row in rows.splitlines()
                  if re.fullmatch('WolfLutris_vastgame_'+re.escape(game)+r'_[0-9]+', row.split()[-1])]
    if not containers: return
    if len(containers) != 1: raise ValueError('Multiple game displays found; no display changed')
    # Execute this small helper in isolation; never replace the running /opt/vastgame files.
    program = globals().get('source') or Path(__file__).read_text()
    try:
        result = subprocess.run(['docker', 'exec', containers[0], 'python3', '-c', program,
                                 'resize', str(width), str(height), label, game, session], timeout=10)
    except subprocess.TimeoutExpired:
        raise ValueError('Game display request timed out; streaming remains available') from None
    if result.returncode: raise SystemExit(result.returncode)


if __name__ == '__main__':
    try:
        if sys.argv[1] == 'host':
            label, game, session, resolution = sys.argv[2:]
            width, height = map(int, resolution.split('x'))
        else:
            width, height = map(int, sys.argv[2:4]); label, game, session = sys.argv[4:]
        if (not re.fullmatch(r'vastgame-[0-9]+', label)
                or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{0,63}', game)
                or not re.fullmatch(r'[a-f0-9]{32}', session)
                or any(not 128 <= dimension <= 16384 or dimension % 2 for dimension in (width, height))):
            raise ValueError('Invalid display request; no display changed')
        if sys.argv[1] == 'host': host(label, game, session, width, height)
        else: resize(width, height, label, game, session)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise SystemExit('Display update: '+str(exc))
