from support import cli_source
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/runtime'))
import game_session as session
import configure_wolf as wolf


def manifest():
    return {'schema': 1, 'id': 'fixture', 'name': 'Fixture',
            'game': {'executable': 'Folder/Game.exe', 'working_dir': 'Folder',
                     'arguments': ['--name', 'with spaces', '$(not-a-command)']},
            'runner': {'type': 'wine', 'version': 'ge-proton'},
            'environment': {'CUSTOM': 'a: b "c"'}}


CONFIG = '''config_version = 4
uuid = "keep-identity"
[[paired_clients]]
client_cert = "keep-client"
[[profiles]]
id = "moonlight-profile-id"
[[profiles.apps]]
title = "Wolf UI"
[profiles.apps.runner]
type = "docker"
image = "wolf-ui"
[[profiles]]
id = "user"
[[profiles.apps]]
title = "Lutris"
[profiles.apps.runner]
type = "docker"
name = "WolfLutris"
image = "ghcr.io/games-on-whales/lutris:edge"
mounts = ["/old/lutris:/var/lutris/:rw", "/etc/wolf/umu/umu-run:/usr/local/bin/umu-run:ro"]
env = ["RUN_SWAY=1", "RUN_GAMESCOPE=1"]
ports = []
devices = []
base_create_json = '{"HostConfig":{"IpcMode":"host"}}'
'''


class SessionTests(unittest.TestCase):
    def test_game_telemetry_keeps_caps_and_uses_hidden_managed_collection(self):
        from types import SimpleNamespace
        m=manifest(); m['environment']['MANGOHUD_CONFIG']='fps_limit=90,no_display=0,log_interval=0'
        collector=SimpleNamespace(folder=Path('/home/retro/.local/state/vastgame/performance/fixture/run'), control='vastgame-run-')
        cfg=session.config(m,collector)
        env=cfg['system']['env']
        self.assertEqual(env['MANGOHUD'],'1')
        self.assertTrue(cfg['system']['mangohud'])
        self.assertIn('fps_limit=90',env['MANGOHUD_CONFIG'])
        self.assertIn('alpha=0',env['MANGOHUD_CONFIG'])
        self.assertIn('background_alpha=0',env['MANGOHUD_CONFIG'])
        self.assertNotIn('no_display=0',env['MANGOHUD_CONFIG'])
        self.assertNotIn('no_display=1',env['MANGOHUD_CONFIG'])
        self.assertIn('log_interval=500',env['MANGOHUD_CONFIG'])
        self.assertIn('control=vastgame-run-%p',env['MANGOHUD_CONFIG'])
        self.assertIn('permit_upload=0',env['MANGOHUD_CONFIG'])

    def test_native_launch_disables_inherited_upscaler(self):
        m = manifest()
        self.assertEqual(session.config(m)['system']['env']['WINE_FULLSCREEN_FSR'], '0')
        m['environment']['WINE_FULLSCREEN_FSR'] = '1'
        self.assertEqual(session.config(m)['system']['env']['WINE_FULLSCREEN_FSR'], '1')

    def test_native_resolution_ignores_desktop_scale(self):
        cli = cli_source()
        helper = cli[cli.index('native_screen_resolution() {'):cli.index('\nlaunch_moonlight()')]
        screen = {'outputs': [{'connected': True, 'enabled': True, 'priority': 1,
                  'scale': 2, 'rotation': 1, 'preferredModes': ['1'], 'currentModeId': '1',
                  'modes': [{'id': '1', 'size': {'width': 2944, 'height': 1840}}]}]}
        import os
        for rotation, expected in [(1, '2944x1840'), (2, '1840x2944')]:
            screen['outputs'][0]['rotation'] = rotation
            result = subprocess.run(['bash', '-c',
                'kscreen-doctor() { printf "%s" "$VASTGAME_TEST_SCREEN_JSON"; }; ' + helper +
                '\nnative_screen_resolution'], capture_output=True, text=True,
                env=dict(os.environ, VASTGAME_TEST_SCREEN_JSON=json.dumps(screen)))
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stdout.strip(), expected)

    def test_encoding_failure_blocks_wolf_start(self):
        boot = (Path(__file__).resolve().parents[1]/'src/bootstrap/start.sh').read_text()
        probe = boot[boot.index('progress_set setup running "Testing CUDA'):boot.index('docker rm -f wolf', boot.index('progress_set setup running "Testing CUDA'))]
        result = subprocess.run(['bash', '-c',
            'progress_set() { :; }; '
            'timeout() { shift; "$@"; }; docker() { echo "$@"; return 1; }; '
            'fail() { echo "$*"; exit 1; }; ' + probe + '\necho READY_TO_START'],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('CUDA video conversion/encoding failed', result.stdout)
        self.assertIn('cudaconvertscale', result.stdout)
        self.assertIn('nvh264enc', result.stdout)
        self.assertNotIn('READY_TO_START', result.stdout)

    def test_final_validation_uses_text_with_old_tomli(self):
        import io
        from types import SimpleNamespace
        boot = (Path(__file__).resolve().parents[1]/'src/bootstrap/start.sh').read_text()
        code = boot.split("<<'PYTOML'", 1)[1].split('\n', 1)[1].split('\nPYTOML', 1)[0]
        def old_loads(text):
            # Old pip-vendored tomli consumes text; load(binary_file) fails here.
            return tomllib.loads(text.replace('\r\n', '\n'))
        for text, valid in [(CONFIG, True), ('broken = [', False)]:
            def open_config(path, mode='r', **kwargs):
                self.assertEqual(path, '/etc/wolf/cfg/config.toml')
                return io.BytesIO(text.encode()) if 'b' in mode else io.StringIO(text)
            with patch.object(wolf, 'tomllib', SimpleNamespace(loads=old_loads)), \
                 patch('builtins.open', side_effect=open_config), patch.object(sys, 'path', sys.path.copy()):
                if valid:
                    exec(code, {})
                else:
                    with self.assertRaises(tomllib.TOMLDecodeError):
                        exec(code, {})

    def test_python310_pip_parser_and_missing_parser(self):
        import builtins
        import runpy
        from types import SimpleNamespace
        original = builtins.__import__
        for pip_available in (True, False):
            def compatible_import(name, *args, **kwargs):
                if name in ('tomllib', 'tomli'):
                    raise ModuleNotFoundError(name)
                if name == 'pip._vendor':
                    if pip_available:
                        return SimpleNamespace(tomli=tomllib)
                    raise ModuleNotFoundError(name)
                return original(name, *args, **kwargs)
            with patch('builtins.__import__', side_effect=compatible_import):
                if pip_available:
                    module = runpy.run_path(str(ROOT/'src/runtime/configure_wolf.py'))
                    text, _ = module['configure'](CONFIG, manifest())
                    self.assertEqual(tomllib.loads(text)['uuid'], 'keep-identity')
                else:
                    with self.assertRaisesRegex(RuntimeError, 'install python3-tomli'):
                        runpy.run_path(str(ROOT/'src/runtime/configure_wolf.py'))

    def test_bootstrap_parser_preflight(self):
        boot = (Path(__file__).resolve().parents[1]/'src/bootstrap/start.sh').read_text()
        block = boot.split('# Check Python compatibility before downloading', 1)[1]
        block = block.split('\n', 1)[1].split('\nprogress_phase BOOT', 1)[0]
        self.assertLess(boot.index(block), boot.index('progress_phase RESTORE'))
        cases = [
            ('python3() { return 0; }; apt-get() { echo UNEXPECTED_INSTALL; return 1; };', 0, False),
            ('python3() { return 1; }; apt-get() { echo INSTALL_FAILED; return 1; };', 1, False),
            ('n=0; python3() { n=$((n+1)); ((n>1)); }; apt-get() { echo "$*"; };', 0, True),
        ]
        for setup, expected, installed in cases:
            result = subprocess.run(['bash', '-c', setup +
                ' timeout() { shift; "$@"; }; fail() { echo "$*"; exit 1; }; ' + block],
                capture_output=True, text=True)
            self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
            self.assertEqual('install -y' in result.stdout, installed)
            self.assertNotIn('UNEXPECTED_INSTALL', result.stdout)

    def test_lutris_api_normalizes_installed_asset_path(self):
        from types import ModuleType, SimpleNamespace
        lutris = ModuleType('lutris')
        util = ModuleType('lutris.util')
        datapath = ModuleType('lutris.util.datapath')
        datapath.get = lambda: '/invalid/share/lutris'
        util.datapath = datapath
        lutris.util = util
        lutris.settings = SimpleNamespace()
        modules = {'lutris': lutris, 'lutris.util': util, 'lutris.util.datapath': datapath,
                   'lutris.startup': SimpleNamespace(init_lutris=lambda: None),
                   'lutris.database': SimpleNamespace(games=SimpleNamespace())}
        with patch.dict(sys.modules, modules), patch.object(Path, 'is_dir', return_value=True):
            settings, _, _ = session.lutris_api()
        self.assertIs(settings, lutris.settings)
        self.assertEqual(datapath.get(), '/usr/share/lutris')

    def test_python310_tomli_fallback(self):
        import builtins
        import runpy
        original = builtins.__import__
        def compatible_import(name, *args, **kwargs):
            if name == 'tomllib':
                raise ModuleNotFoundError("No module named 'tomllib'")
            if name == 'tomli':
                return tomllib
            return original(name, *args, **kwargs)
        with patch('builtins.__import__', side_effect=compatible_import):
            module = runpy.run_path(str(ROOT/'src/runtime/configure_wolf.py'))
        text, title = module['configure'](CONFIG, manifest())
        self.assertIn(title, [a['title'] for a in tomllib.loads(text)['profiles'][0]['apps']])

    def test_wolf_failure_keeps_original_exception(self):
        boot = (Path(__file__).resolve().parents[1]/'src/bootstrap/start.sh').read_text()
        command = next(line for line in boot.splitlines() if line.startswith('  wolf_error='))
        result = subprocess.run(['bash', '-c',
            'python3() { echo "ModuleNotFoundError: test parser" >&2; return 1; }; '
            'fail() { echo "$*"; exit 1; }; CFG=x; GAME_ID=fixture; ' + command],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('Direct Wolf app configuration failed: ModuleNotFoundError: test parser', result.stdout)

    def test_config_preserves_args_and_environment(self):
        import shlex
        m = manifest()
        c = session.config(m)
        self.assertEqual(shlex.split(c['game']['args']), m['game']['arguments'])
        self.assertEqual(c['system']['env']['CUSTOM'], m['environment']['CUSTOM'])
        self.assertEqual(c['game']['prefix'], '/prefixes/fixture')

    def test_register_uses_lutris_database_and_exact_config(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); exe = root/'Game.exe'; exe.touch()
            c = session.config(manifest())
            c['game'].update(exe=str(exe), working_dir=str(root), prefix=str(root/'prefix'))
            init = Mock(); add = Mock(return_value=42)
            modules = {'lutris': SimpleNamespace(settings=SimpleNamespace(GAME_CONFIG_DIR=str(root))),
                       'lutris.startup': SimpleNamespace(init_lutris=init),
                       'lutris.database': SimpleNamespace(games=SimpleNamespace(add_or_update=add))}
            with patch.dict(sys.modules, modules), patch.object(session, 'config', return_value=c):
                self.assertEqual(session.register(manifest()), '42')
                init.assert_called_once()
                self.assertEqual(add.call_args.kwargs['configpath'], 'vastgame-fixture')
                self.assertEqual(json.loads((root/'vastgame-fixture.yml').read_text()), c)
                exe.unlink()
                with self.assertRaisesRegex(FileNotFoundError, 'executable is missing'):
                    session.register(manifest())
                self.assertEqual(add.call_count, 1)
                # Setup may register the expected path before files arrive, but
                # the normal launch path must still reject that missing EXE.
                self.assertEqual(session.register(manifest(), preparing=True), '42')
                with self.assertRaises(FileNotFoundError):
                    session.register(manifest())
                self.assertEqual(add.call_count, 2)

    def test_reject_unsafe_paths(self):
        for path in ['/tmp/game.exe', '../game.exe', 'a/../../bad', 'a\\..\\bad']:
            m = manifest(); m['game']['executable'] = path
            with self.assertRaises(ValueError): session.validate(m)

    def test_dlss_preserves_other_overrides(self):
        m = manifest(); m['graphics'] = {'dlss': True}
        m['environment']['WINEDLLOVERRIDES'] = 'dinput8=n,b;nvngx=b'
        env = session.config(m)['system']['env']
        self.assertEqual(env['WINEDLLOVERRIDES'], 'dinput8=n,b;nvngx,_nvngx=n,b')
        self.assertEqual(env['PROTON_ENABLE_NVAPI'], '1')
        self.assertEqual(env['DISABLE_GAMESCOPE_WSI'], '1')
        self.assertEqual(session.config(m)['wine']['overrides'],
                         {'dinput8': 'n,b', 'nvngx': 'n,b', '_nvngx': 'n,b'})
        m['environment']['DISABLE_GAMESCOPE_WSI'] = '0'
        self.assertEqual(session.config(m)['system']['env']['DISABLE_GAMESCOPE_WSI'], '0')

    def test_nvidia_compatibility_is_separate_from_graphics_choices(self):
        from compatibility import nvidia_ngx_enabled
        m = manifest(); m['graphics'] = {'dlss': True, 'path_tracing': True}
        self.assertTrue(nvidia_ngx_enabled(m))
        m['compatibility'] = {'nvidia_ngx': False}
        self.assertFalse(nvidia_ngx_enabled(m))
        self.assertNotIn('PROTON_ENABLE_NVAPI', session.config(m)['system']['env'])
        m['compatibility']['nvidia_ngx'] = True
        m.pop('graphics')
        before = json.dumps(m, sort_keys=True)
        c = session.config(m)
        self.assertEqual(c['system']['env']['PROTON_ENABLE_NVAPI'], '1')
        self.assertEqual(c['game']['args'], session.shlex.join(m['game']['arguments']))
        self.assertEqual(json.dumps(m, sort_keys=True), before)
        for value in ('true', 1, None):
            m['compatibility']['nvidia_ngx'] = value
            with self.assertRaisesRegex(ValueError, 'boolean'):
                session.validate(m)

    def test_dlss_cli_preserves_game_arguments_and_custom_runner(self):
        cli = cli_source()
        functions = cli[cli.index('game_enable_dlss() {'):cli.index('\ngame_inspect()')]
        import os
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp)/'fixture/manifest.json'; dest.parent.mkdir()
            m = manifest(); m['runner']['version'] = 'custom-proton'
            m['graphics'] = {'dlss': False, 'ray_tracing': False, 'path_tracing': False}
            m['package'] = {'sha256': 'unchanged'}
            dest.write_text(json.dumps(m))
            code = 'valid_game_id() { return 0; }; game_manifest() { printf "%s/%s/manifest.json" "$GAME_ROOT" "$1"; }; ok() { :; }; die() { exit 1; }; ' + functions + '\ngame_enable_dlss fixture'
            subprocess.run(['bash', '-e', '-c', code], check=True,
                           env=dict(os.environ, GAME_ROOT=tmp))
            changed = json.loads(dest.read_text())
            self.assertEqual(changed['game'], m['game'])
            self.assertEqual(changed['runner'], m['runner'])
            self.assertEqual(changed['environment'], m['environment'])
            self.assertEqual(changed['package'], m['package'])
            self.assertEqual(changed['compatibility'], {'nvidia_ngx': True})
            self.assertNotIn('graphics', changed)

    def test_add_dlss_is_generic_and_does_not_inject_engine_arguments(self):
        cli = cli_source()
        function = cli[cli.index('game_add() {'):cli.index('\ngame_package()')]
        import os
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp)/'Portal'; source.mkdir(); (source/'Portal.exe').write_bytes(b'MZ'+bytes(58)+(64).to_bytes(4, 'little')+b'PE\0\0')
            root = Path(tmp)/'catalog'
            code = 'valid_game_id() { return 0; }; game_manifest() { printf "%s/%s/manifest.json" "$GAME_ROOT" "$1"; }; ok() { :; }; warn() { :; }; die() { exit 1; }; ' + function + '\ngame_add "$VASTGAME_TEST_SOURCE" fixture --dlss'
            subprocess.run(['bash', '-e', '-c', code], check=True, stdout=subprocess.DEVNULL,
                           env=dict(os.environ, GAME_ROOT=str(root), CLIENT_DIR=str(ROOT/'src/client'), VASTGAME_TEST_SOURCE=str(source)))
            m = json.loads((root/'fixture/manifest.json').read_text())
            self.assertEqual(m['game']['arguments'], [])
            self.assertEqual(m['game']['executable'], 'Portal.exe')
            self.assertEqual(m['compatibility'], {'nvidia_ngx': True})
            self.assertNotIn('graphics', m)

    def test_explicit_wine_debug_reaches_lutris_runner(self):
        m = manifest(); m['environment']['WINEDEBUG'] = '-all,+seh'
        self.assertEqual(session.config(m)['wine']['show_debug'], '-all,+seh')
        self.assertNotIn('show_debug', session.config(manifest())['wine'])

    def test_direct_profile_and_identity(self):
        text, title = wolf.configure(CONFIG, manifest())
        d = tomllib.loads(text)
        self.assertEqual(d['uuid'], 'keep-identity')
        self.assertEqual(d['paired_clients'][0]['client_cert'], 'keep-client')
        app = next(a for a in d['profiles'][0]['apps'] if a['title'] == title)
        self.assertEqual(app['runner']['image'],'vastgame-preparation:v1')
        mounts = app['runner']['mounts']
        self.assertIn('/srv/gaming/prefixes:/prefixes:rw', mounts)
        self.assertIn('/srv/gaming/lutris/fixture:/var/lutris/:rw', mounts)
        self.assertFalse(any('/old/' in x for x in mounts))
        self.assertIn('WOLF_LUTRIS_GAMEPAD_UI_ENABLE=0', app['runner']['env'])
        for value in ('RUN_SWAY=', 'RUN_GAMESCOPE=1', 'GAMESCOPE_MODE=-f'):
            self.assertIn(value, app['runner']['env'])
        self.assertEqual(d['profiles'][1], tomllib.loads(CONFIG)['profiles'][1])

    def test_config_idempotent(self):
        one, _ = wolf.configure(CONFIG, manifest())
        two, _ = wolf.configure(one, manifest())
        self.assertEqual(tomllib.loads(one), tomllib.loads(two))

    def test_missing_profile_fails(self):
        with self.assertRaises(ValueError): wolf.configure(CONFIG.replace('moonlight-profile-id', 'wrong'), manifest())

    def test_process_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); p = root / '100'; p.mkdir()
            (p/'cmdline').write_bytes(b'lutris\0-d\0lutris:rungameid/1\0')
            (p/'environ').write_bytes(b'WINEPREFIX=/prefixes/fixture\0')
            self.assertFalse(session.process_seen('/games/fixture/Game.exe', '/prefixes/fixture', root))
            (p/'cmdline').write_bytes(b'Z:\\games\\fixture\\Game.exe\0')
            self.assertTrue(session.process_seen('/games/fixture/Game.exe', '/prefixes/fixture', root))
            (p/'cmdline').write_bytes(b'Other.exe\0')
            self.assertFalse(session.process_seen('/games/fixture/Game.exe', '/prefixes/fixture', root))

    def test_wrapper_roundtrip_and_budget(self):
        code = (ROOT/'src/bootstrap/pack.py').read_text()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); script = root/'pack.py'; script.write_text(code)
            output = root/'onstart.sh'
            subprocess.run([sys.executable, str(script), str(ROOT/'src/bootstrap/start.sh'), str(output), 'vastgame-1234567890', '123456', 'fixture'], check=True)
            self.assertLess(output.stat().st_size, 15360)
            wrapper = output.read_text()
            self.assertIn('if [ ! -d /run/systemd/system ]; then', wrapper)
            self.assertLess(wrapper.index('Bootstrap did not enter'), wrapper.index('python3 -c'))
            subprocess.run(['sh', '-n', str(output)], check=True)
            import base64, lzma
            payload = output.read_text().split("VASTGAME_BOOTSTRAP_B85' | xz -dc > \"$tmp\"\n", 1)[1].split('\nVASTGAME_BOOTSTRAP_B85', 1)[0]
            decoded = lzma.decompress(base64.b85decode(payload))
            subprocess.run(['bash', '-n'], input=decoded, check=True)


if __name__ == '__main__': unittest.main()
