# Wine/NVIDIA launch support; in-game graphics choices belong to the game.
import re


def nvidia_ngx_enabled(manifest):
    compatibility = manifest.get('compatibility', {})
    if not isinstance(compatibility, dict):
        raise ValueError('Compatibility must be an object')
    legacy = manifest.get('graphics', {})
    if not isinstance(legacy, dict):
        raise ValueError('Legacy graphics must be an object')
    enabled = compatibility.get('nvidia_ngx', legacy.get('dlss', False))
    if not isinstance(enabled, bool):
        raise ValueError('NVIDIA NGX compatibility must be a boolean')
    return enabled


def wine_config(manifest):
    env = dict(manifest.get('environment', {}))
    env.setdefault('WINE_FULLSCREEN_FSR', '0')
    env.update(PROTON_LOG='1', PROTON_LOG_DIR=f'/profiles/{manifest["id"]}/logs')
    cache = f'/shaders/{manifest["id"]}/cache'
    env.update(DXVK_SHADER_CACHE_PATH=cache, DXVK_STATE_CACHE_PATH=cache, VKD3D_SHADER_CACHE_PATH=cache,
               __GL_SHADER_DISK_CACHE='1', __GL_SHADER_DISK_CACHE_PATH=cache,
               __GL_SHADER_DISK_CACHE_SKIP_CLEANUP='1')
    if nvidia_ngx_enabled(manifest):
        env['PROTON_ENABLE_NVAPI'] = '1'
        env.setdefault('DISABLE_GAMESCOPE_WSI', '1')
        overrides = [s for s in env.get('WINEDLLOVERRIDES', '').split(';')
                     if s and not re.search(r'(^|,)_?nvngx([,=]|$)', s)]
        env['WINEDLLOVERRIDES'] = ';'.join(overrides + ['nvngx,_nvngx=n,b'])
    wine = {'version': manifest.get('runner', {}).get('version', 'ge-proton')}
    if 'WINEDEBUG' in env:
        wine['show_debug'] = env['WINEDEBUG']
    # Lutris regenerates these variables from its Wine runner options.
    overrides = {}
    for entry in env.get('WINEDLLOVERRIDES', '').split(';'):
        if '=' in entry:
            names, order = entry.split('=', 1)
            overrides.update((name.strip(), order) for name in names.split(',') if name.strip())
    if overrides:
        wine['overrides'] = overrides
    return wine, env
