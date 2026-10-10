"""Private preferences shared by desktop settings, host ranking and Moonlight."""
import argparse
import fcntl
import json
import math
import os
from pathlib import Path
import re
import tempfile

from stream_settings import read as read_stream, validate as validate_stream

COUNTRIES = json.loads(Path(__file__).with_name('countries.json').read_text())
DEFAULTS = dict(country='', preferred_gpu='', spending_limit_usd=0,
                verified_only=False, min_download_mbps=0, min_upload_mbps=0,
                min_vram_gb=0, min_ram_gb=0)
STREAM_KEYS = {'video_codec', 'fps', 'resolution', 'bitrate_mbps',
               'video_decoder', 'display_mode', 'moonlight_options'}
OPTION_KEYS = {'vsync', 'frame-pacing', 'yuv444', 'audio-config'}


def validate_hosts(data):
    if not isinstance(data, dict) or set(data) - set(DEFAULTS):
        raise ValueError('Unknown host preference')
    result = {**DEFAULTS, **data}
    if not isinstance(result['country'], str) or (result['country'] != '' and result['country'] not in COUNTRIES):
        raise ValueError('Choose a valid country')
    gpu = result['preferred_gpu']
    if not isinstance(gpu, str) or len(gpu) > 80 or re.search(r'[\x00-\x1f]', gpu):
        raise ValueError('Invalid GPU preference')
    if type(result['verified_only']) is not bool:
        raise ValueError('Verified hosts must be on or off')
    for key, maximum in [('spending_limit_usd', 100000), ('min_download_mbps', 100000),
                         ('min_upload_mbps', 100000), ('min_vram_gb', 1024), ('min_ram_gb', 65536)]:
        value = result[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= maximum:
            raise ValueError(f'Invalid {key}: use a number between 0 and {maximum}')
    return result


def read_hosts(config):
    path = Path(config) / 'host_preferences.json'
    if not path.exists():
        return dict(DEFAULTS)
    if path.stat().st_size > 65536:
        raise ValueError('Host preferences file is too large')
    return validate_hosts(json.loads(path.read_text(encoding='utf-8-sig')))


def ranking(config):
    settings = read_hosts(config)
    origin = COUNTRIES.get(settings['country'], {}).get('point')
    points = {}
    if origin:
        latitude, longitude = map(math.radians, origin)
        for code, entry in COUNTRIES.items():
            target = entry.get('point')
            if not target:
                continue
            lat, lon = map(math.radians, target)
            haversine = math.sin((lat-latitude)/2)**2 + math.cos(lat)*math.cos(latitude)*math.sin((lon-longitude)/2)**2
            distance = 12742 * math.asin(math.sqrt(min(1, max(0, haversine))))
            points[code] = round(15 / (1 + distance / 1500), 3)
    return {**settings, 'country_points': points}


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('Preferences must use a regular file, not a symlink')
    fd, temporary = tempfile.mkstemp(prefix='.settings-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data if isinstance(data, bytes) else
                         (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))
            output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path)
        # Windows stream.json can live on DrvFS, which does not support directory fsync.
        if not str(path).startswith('/mnt/'):
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try: os.fsync(directory)
            finally: os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def preferences(config, stream, windows=False, patch=None, reset=False):
    config = Path(config)
    config.mkdir(parents=True, exist_ok=True)
    fd = os.open(config / '.settings.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current_stream, hosts = (validate_stream({}, windows), dict(DEFAULTS)) if reset else (read_stream(stream, windows), read_hosts(config))
        if reset: patch = dict(stream={}, hosts={})
        if patch is not None:
            if not isinstance(patch, dict) or not patch or not set(patch) <= {'stream', 'hosts'}:
                raise ValueError('Invalid settings request')
            writes = {}
            if 'stream' in patch:
                data = patch['stream']
                if not isinstance(data, dict) or set(data) - STREAM_KEYS:
                    raise ValueError('Unknown streaming preference')
                options = data.get('moonlight_options', {})
                if not isinstance(options, dict) or set(options) - OPTION_KEYS:
                    raise ValueError('Unknown streaming option')
                data = {**data, 'moonlight_options': {**current_stream['moonlight_options'], **options}}
                current_stream = validate_stream({**current_stream, **data}, windows)
                writes[Path(stream)] = current_stream
            if 'hosts' in patch:
                if not isinstance(patch['hosts'], dict):
                    raise ValueError('Invalid host preferences')
                hosts = validate_hosts({**hosts, **patch['hosts']})
                writes[config / 'host_preferences.json'] = hosts
            # Validate both groups and destinations before changing either file.
            originals = {}
            for path in writes:
                if path.is_symlink():
                    raise ValueError('Preferences must use a regular file, not a symlink')
                originals[path] = path.read_bytes() if path.exists() else None
            changed = []
            try:
                for path, data in writes.items():
                    changed.append(path)
                    atomic_write(path, data)
            except (OSError, ValueError) as failure:
                rollback_errors = []
                for path in reversed(changed):
                    try:
                        if originals[path] is None:
                            path.unlink(missing_ok=True)
                        elif not path.exists() or path.read_bytes() != originals[path]:
                            atomic_write(path, originals[path])
                    except (OSError, ValueError):
                        rollback_errors.append(path.name)
                if rollback_errors:
                    raise OSError('Settings save failed; rollback incomplete for ' + ', '.join(rollback_errors)) from failure
                raise
        return dict(settings=dict(stream=current_stream, hosts=hosts),
                    countries=[dict(value=code, label=item['name']) for code, item in
                               sorted(COUNTRIES.items(), key=lambda row: row[1]['name'])])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['get', 'save', 'rank', 'reset'])
    parser.add_argument('--stream-path')
    parser.add_argument('--windows', action='store_true')
    parser.add_argument('--patch')
    args = parser.parse_args()
    config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'vastgame'
    try:
        if args.action == 'rank':
            result = ranking(config)
        else:
            if not args.stream_path or (args.action == 'save' and (not args.patch or len(args.patch) > 65536)):
                raise ValueError('Invalid settings request')
            result = preferences(config, args.stream_path, args.windows,
                                 json.loads(args.patch) if args.action == 'save' else None, reset=args.action == 'reset')
        print(json.dumps(result, allow_nan=False))
    except (OSError, ValueError, TypeError) as exc:
        if args.action == 'rank':
            parser.exit(1, f'Cannot read host preferences: {exc}\n')
        print(json.dumps(dict(error=dict(code='SETTINGS_INVALID', message=str(exc)))))
