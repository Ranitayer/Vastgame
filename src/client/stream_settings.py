"""Validate stream preferences and build Moonlight arguments without shell evaluation."""
import json
from pathlib import Path
import re
import sys

TOGGLES = {
    'vsync', 'multi-controller', 'quit-after', 'absolute-mouse', 'mouse-buttons-swap',
    'touchscreen-trackpad', 'game-optimization', 'audio-on-host', 'frame-pacing',
    'mute-on-focus-loss', 'background-gamepad', 'reverse-scroll-direction',
    'swap-gamepad-buttons', 'keep-awake', 'performance-overlay', 'hdr', 'yuv444',
}
CHOICES = {
    'audio-config': {'stereo', '5.1-surround', '7.1-surround'},
    'capture-system-keys': {'never', 'fullscreen', 'always'},
}


def resolution(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]+x[0-9]+', value):
        raise ValueError('resolution must be "native" or WIDTHxHEIGHT, such as "1920x1080"')
    if not all(128 <= n <= 16384 and n % 2 == 0 for n in map(int, value.split('x'))):
        raise ValueError('resolution dimensions must be even numbers between 128 and 16384')
    return value


def validate(data, windows=False):
    config = dict(resolution='native', fps='native', bitrate_mbps=None,
                  video_codec='AV1' if windows else 'auto', video_decoder='auto',
                  display_mode='fullscreen', moonlight_options={})
    if not isinstance(data, dict) or set(data) - set(config):
        raise ValueError('Unknown stream setting; use the documented stream.json keys')
    config.update(data)
    if config['resolution'] != 'native':
        resolution(config['resolution'])
    fps = config['fps']
    if fps != 'native' and (type(fps) is not int or not 1 <= fps <= 1000):
        raise ValueError('fps must be "native" or an integer from 1 to 1000')
    bitrate = config['bitrate_mbps']
    if bitrate is not None and (type(bitrate) not in (int, float) or not 1 <= bitrate <= 500):
        raise ValueError('bitrate_mbps must be null or a number from 1 to 500')
    for key, allowed in (
        ('video_codec', {'auto', 'H.264', 'HEVC', 'AV1'}),
        ('video_decoder', {'auto', 'hardware', 'software'}),
        ('display_mode', {'fullscreen', 'windowed', 'borderless'}),
    ):
        if not isinstance(config[key], str) or config[key] not in allowed:
            raise ValueError(f'{key} must be one of: {", ".join(sorted(allowed))}')
    options = config['moonlight_options']
    if not isinstance(options, dict):
        raise ValueError('moonlight_options must be an object')
    for key, value in options.items():
        if key in TOGGLES:
            if type(value) is not bool:
                raise ValueError(f'moonlight_options.{key} must be true or false')
        elif key in CHOICES:
            if not isinstance(value, str) or value not in CHOICES[key]:
                raise ValueError(f'Invalid moonlight_options.{key}')
        elif key == 'packet-size':
            if type(value) is not int or not 256 <= value <= 1400:
                raise ValueError('packet-size must be an integer from 256 to 1400')
        else:
            raise ValueError(f'Unknown Moonlight stream option: {key}')
    config['moonlight_options'] = {
        'absolute-mouse': False, 'multi-controller': True,
        'capture-system-keys': 'never', 'performance-overlay': True, **options,
    }
    return config


def read(path, windows=False):
    path = Path(path)
    if not path.exists():
        return validate({}, windows)
    if path.stat().st_size > 65536:
        raise ValueError('Stream settings file is too large')
    return validate(json.loads(path.read_text(encoding='utf-8-sig')), windows)


def resolve(config, native_resolution, native_fps):
    config = dict(config)
    config['resolution'] = resolution(native_resolution if config['resolution'] == 'native' else config['resolution'])
    fps = int(native_fps) if config['fps'] == 'native' else config['fps']
    if not 1 <= fps <= 1000:
        raise ValueError('Invalid detected screen refresh rate')
    config['fps'] = fps
    args = ['--resolution', config['resolution'], '--fps', str(fps),
            '--display-mode', config['display_mode'], '--video-codec', config['video_codec'],
            '--video-decoder', config['video_decoder']]
    if config['bitrate_mbps'] is not None:
        args += ['--bitrate', str(round(config['bitrate_mbps'] * 1000))]
    for key, value in config['moonlight_options'].items():
        args += [('--' if value else '--no-') + key] if key in TOGGLES else ['--'+key, str(value)]
    config['args'] = args
    return config


if __name__ == '__main__':
    try:
        mode, path, windows, *native = sys.argv[1:]
        config = read(path, windows == '1')
        if mode == 'resolve':
            config = resolve(config, *native)
        elif mode != 'read':
            raise ValueError('Invalid settings operation')
        print(json.dumps(config))
    except (ValueError, OSError, TypeError) as exc:
        print(f'Invalid stream settings: {exc}', file=sys.stderr)
        sys.exit(1)
