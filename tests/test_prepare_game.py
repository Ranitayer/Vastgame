from support import cli_source
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/runtime'))
import prepare_game as prep
import configure_wolf as wolf
from test_game_session import CONFIG, manifest


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'profiles/fixture').mkdir(parents=True)
        self.runner = Mock()
        self.runner.get_command.return_value = ['/opt/umu/umu-run']
        self.runner.get_env.return_value = {'PROTONPATH':'GE-Proton'}
        self.runner.get_dll_managers.return_value = {}
        self.calls = []

    def path(self, value, *args):
        text = str(value)
        if text == '/profiles' or text == '/prefixes' or text == '/shaders' or text.startswith(('/profiles/', '/prefixes/', '/shaders/')):
            return Path(self.root/text.lstrip('/'), *args)
        return Path(value, *args)

    def initialize(self, command, **kwargs):
        self.calls.append((command, kwargs))
        p = self.root/'prefixes/fixture'; p.mkdir(parents=True,exist_ok=True)
        for name in ('user.reg','userdef.reg','system.reg','drive_c/windows/system32/cmd.exe'):
            dest = p/name; dest.parent.mkdir(parents=True,exist_ok=True); dest.write_bytes(b'initialized')
        return Mock(returncode=0)

    def run_prepare(self, execute=None):
        with patch.object(prep,'Path',side_effect=self.path), patch.object(prep,'progress') as progress, patch.object(prep.subprocess,'run',side_effect=execute or self.initialize):
            prep.prepare(manifest(),self.runner)
        return progress

    def test_setup_uses_selected_runner_and_never_game_executable(self):
        progress = self.run_prepare()
        self.assertEqual(len(self.calls),2)
        for command, kwargs in self.calls:
            self.assertEqual(command,['/opt/umu/umu-run','cmd.exe','/c','exit','0'])
            self.assertEqual(kwargs['env']['PROTONPATH'],'GE-Proton')
            self.assertEqual(kwargs['env']['WINEPREFIX'],'/prefixes/fixture')
            self.assertNotIn('Game.exe',command)
            self.assertTrue(kwargs['check'])
        self.runner.get_executable.assert_called_once_with(fallback=False)
        self.runner.prelaunch.assert_called_once()
        self.assertTrue((self.root/'profiles/fixture/prepared.json').exists())
        for key in ('proton','prefix','dx12'):
            self.assertTrue(any(c.args[0]==key and c.args[1]=='done' for c in progress.call_args_list))

    def test_runtime_download_failure_never_marks_ready(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_prepare(lambda *a,**k: (_ for _ in ()).throw(subprocess.CalledProcessError(1,a[0])))
        self.assertFalse((self.root/'profiles/fixture/prepared.json').exists())
        self.runner.prelaunch.assert_not_called()

    def test_zero_exit_without_real_prefix_is_failure(self):
        with self.assertRaisesRegex(RuntimeError,'valid game prefix'):
            self.run_prepare(lambda *a,**k: Mock(returncode=0))
        self.assertFalse((self.root/'profiles/fixture/prepared.json').exists())

    def test_dx12_download_failure_prevents_ready(self):
        manager = Mock()
        manager.version = 'v2'; manager.versions_path=str(self.root/'versions.json')
        manager.base_dir = str(self.root/'runtime'); manager.human_name = 'VKD3D'
        manager.is_available.return_value=False; manager.download.return_value=False
        self.runner.get_dll_managers.return_value={manager:True}
        with self.assertRaisesRegex(RuntimeError,'VKD3D'): self.run_prepare()
        self.assertFalse((self.root/'profiles/fixture/prepared.json').exists())

    def test_cached_x64_bundle_does_not_require_absent_x86_dlls(self):
        manager=Mock(); manager.version='v2'; manager.human_name='VKD3D'
        manager.path=str(self.root/'runtime/vkd3d/v2'); manager.managed_dlls=('d3d12',)
        manager.versions_path=str(self.root/'versions.json'); Path(manager.versions_path).write_text('[]')
        source=Path(manager.path)/'x64/d3d12.dll'; source.parent.mkdir(parents=True); source.write_bytes(b'DX12')
        native=self.root/'prefixes/fixture/drive_c/windows/system32'
        wow=self.root/'prefixes/fixture/drive_c/windows/syswow64'
        manager._iter_dlls.return_value=[(str(native),'x64','d3d12'),(str(wow),'x86','d3d12')]
        manager.is_available.return_value=True
        self.runner.get_dll_managers.return_value={manager:True}
        self.runner.prelaunch.side_effect=lambda: (native/'d3d12.dll').write_bytes(b'DX12')
        self.run_prepare()
        manager.download.assert_not_called()
        self.assertTrue((self.root/'profiles/fixture/prepared.json').exists())

    def test_ready_marker_rejects_changed_manifest(self):
        self.run_prepare()
        m=manifest(); m['runner']['version']='another-runner'
        with patch.object(prep,'Path',side_effect=self.path):
            with self.assertRaisesRegex(RuntimeError,'not prepared'): prep.require_ready(m)

    def test_save_mapping_and_local_source_changes_do_not_invalidate_preparation(self):
        self.run_prepare()
        m=manifest(); m['state']={'saves':['drive_c/users/user/new-save']}; m['source']={'path':'/another/local/path'}
        with patch.object(prep,'Path',side_effect=self.path):
            prep.require_ready(m)

    def test_preparation_and_stream_use_same_cache_mounts(self):
        text,title=wolf.configure(CONFIG,manifest())
        import tomllib
        app=next(a for a in tomllib.loads(text)['profiles'][0]['apps'] if a['title']==title)
        mounts=app['runner']['mounts']
        for mount in ('/srv/gaming/lutris/fixture/home/.local:/home/retro/.local:rw',
                      '/srv/gaming/lutris/fixture/home/.config:/home/retro/.config:rw',
                      '/srv/gaming/lutris/fixture/home/.cache:/home/retro/.cache:rw'):
            self.assertIn(mount,mounts)
        self.assertNotIn('/home/retro',[s.split(':')[1].rstrip('/') for s in mounts])
        boot=(Path(__file__).resolve().parents[1]/'src/bootstrap/start.sh').read_text()
        self.assertLess(boot.index('timeout --foreground 2400 docker run'),boot.index('progress_phase WOLF'))
        self.assertLess(boot.index('/opt/vastgame/prepare-game.sh'),boot.index('python3 /opt/vastgame/game_state.py restore'))

    def test_preparation_display_does_not_need_gamescope_or_gpu_formats(self):
        script=(ROOT/'src/runtime/prepare-game.sh').read_text()
        launch=next(line for line in script.splitlines() if line.startswith('xvfb-run '))
        self.assertIn('-nolisten tcp',launch)
        self.assertIn('dbus-run-session',launch)
        self.assertNotIn('--backend headless',script)
        boot=(Path(__file__).resolve().parents[1]/'src/bootstrap/start.sh').read_text()
        self.assertIn('FROM ghcr.io/games-on-whales/lutris:edge',boot)
        self.assertIn('--no-install-recommends xvfb xauth',boot)
        self.assertIn('--entrypoint /bin/bash vastgame-preparation:v1',boot)

    def test_preparation_mounts_are_provisioned_before_container_runs(self):
        boot=(Path(__file__).resolve().parents[1]/'src/bootstrap/start.sh').read_text()
        start=boot.index('  # All writable preparation mounts')
        stop=boot.index('  progress_set proton running', start)
        block=boot[start:stop].replace('/srv/gaming', str(self.root/'gaming')).replace('/var/lib/vast-gaming/status', str(self.root/'status'))
        cache=self.root/'gaming/shaders/fixture/cache'; cache.mkdir(parents=True)
        cache.chmod(0o555)
        (self.root/'status').mkdir()
        commands=self.root/'ownership.txt'
        result=subprocess.run(['bash','-e','-c',
            'GAME_ID=fixture; RETRO_UID=1000; RETRO_GID=1000; '
            'chown() { printf "%s\\n" "$@" >> "$OWNERSHIP_LOG"; }; '+block],
            env=dict(os.environ,OWNERSHIP_LOG=str(commands)),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn(str(cache.parent),commands.read_text())
        self.assertIn('1000:1000',commands.read_text())
        with tempfile.TemporaryFile(dir=cache): pass
        self.assertLess(stop,boot.index('timeout --foreground 2400 docker run',stop))
        self.assertNotIn('/gaming/games',commands.read_text())

    def test_container_preflight_checks_real_writes_and_reports_readonly_mount(self):
        home=self.root/'home'; home.mkdir()
        def mounted(value, *args):
            return Path(self.root/str(value).lstrip('/'),*args)
        factory=Mock(side_effect=mounted); factory.home.return_value=home
        with patch.object(prep,'Path',factory):
            prep.check_writable_paths(manifest())
            cache=self.root/'shaders/fixture/cache'; cache.chmod(0o555)
            try:
                with self.assertRaisesRegex(RuntimeError,'cannot write .*shaders/fixture/cache'):
                    prep.check_writable_paths(manifest())
            finally:
                cache.chmod(0o755)

    def test_runtime_publication_compares_contents_not_modtime(self):
        cli=cli_source()
        upload=next(line for line in cli.splitlines() if 'rclone copyto "$archive"' in line)
        self.assertIn('--immutable --checksum',upload)
        self.assertIn('Runtime readback checksum failed',cli)

    def test_fresh_proton_prefix_architecture_is_explicit(self):
        import game_session
        m=manifest()
        self.assertEqual(game_session.config(m)['game']['arch'],'win64')
        m['runner']['version']='wine-staging'
        self.assertEqual(game_session.config(m)['game']['arch'],'auto')

    def test_gamescope_captures_cursor_without_combining_flags(self):
        hook=ROOT/'src/runtime/90-vastgame.sh'
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'gamescope'
            exe.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n'); exe.chmod(0o755)
            r=subprocess.run(['bash','-c','source "$VASTGAME_HOOK"; "$(command -v gamescope)" -f -W 2944 -H 1840 -r 90'],env=dict(os.environ,PATH=tmp+':'+os.environ['PATH'],VASTGAME_HOOK=str(hook)),capture_output=True,text=True,check=True)
            self.assertEqual(r.stdout.splitlines(),['--force-grab-cursor','-f','-W','2944','-H','1840','-r','90'])

    def test_native_refresh_and_relative_mouse_options(self):
        cli=cli_source()
        helper=cli[cli.index('native_screen_resolution() {'):cli.index('\nlaunch_moonlight()')]
        screen={'outputs':[dict(connected=True,enabled=True,priority=1,rotation=1,scale=2,preferredModes=['60'],currentModeId='90',modes=[dict(id='60',size=dict(width=2944,height=1840),refreshRate=59.999),dict(id='90',size=dict(width=2944,height=1840),refreshRate=89.999)])]}
        r=subprocess.run(['bash','-c','kscreen-doctor() { printf "%s" "$SCREEN"; }; '+helper+'\nmoonlight_game_options'],env=dict(os.environ,SCREEN=json.dumps(screen)),capture_output=True,text=True,check=True)
        opts=r.stdout.splitlines()
        self.assertEqual(opts[opts.index('--resolution')+1],'2944x1840')
        self.assertEqual(opts[opts.index('--fps')+1],'90')
        self.assertIn('--no-absolute-mouse',opts); self.assertIn('--multi-controller',opts)
        self.assertEqual(opts[opts.index('--capture-system-keys')+1],'never')


if __name__=='__main__': unittest.main()

class PreparedEnvironmentTests(unittest.TestCase):
    def test_installed_umu_needs_no_runtime_download(self):
        from types import SimpleNamespace
        class Missing(Exception): pass
        lookup=Mock(return_value='/installed/umu-run')
        with patch.dict(sys.modules,{'lutris.util.wine.proton':SimpleNamespace(get_umu_path=lookup),
                                     'lutris.exceptions':SimpleNamespace(MissingExecutableError=Missing)}):
            self.assertEqual(prep.ensure_umu(),'/installed/umu-run')

    def test_missing_umu_uses_installed_catalogue_without_gui_callbacks(self):
        from types import SimpleNamespace
        class Missing(Exception): pass
        with tempfile.TemporaryDirectory() as tmp:
            lookup=Mock(side_effect=[Missing(),'/runtime/umu/umu-run'])
            component=Mock(); component.name='umu'; component.url='https://example.invalid/umu.tar.gz'
            component.archive_path=str(Path(tmp)/'umu.tar.gz')
            updater=Mock(); updater._get_runtime_updaters.return_value=[component]
            constructor=Mock(return_value=updater); download=Mock()
            modules={'lutris.util.wine.proton':SimpleNamespace(get_umu_path=lookup),
                     'lutris.exceptions':SimpleNamespace(MissingExecutableError=Missing),
                     'lutris.runtime':SimpleNamespace(RuntimeUpdater=constructor),
                     'lutris.util':SimpleNamespace(http=SimpleNamespace(download_file=download))}
            with patch.dict(sys.modules,modules),patch.object(prep,'progress'):
                self.assertEqual(prep.ensure_umu(),'/runtime/umu/umu-run')
            constructor.assert_called_once_with(force=True)
            download.assert_called_once_with(component.url,component.archive_path)
            component._install.assert_called_once_with(component.archive_path)
            component.install_update.assert_not_called()

    def test_exact_proton_build_is_kept_and_runtime_updates_wait_for_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'proton').touch()
            env={'PROTONPATH':str(root)}
            self.assertEqual(prep.pin_environment(env,['/opt/umu/umu-run']),{'PROTONPATH':str(root),'UMU_RUNTIME_UPDATE':'0'})

    def test_ge_token_pins_single_prepared_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'.local/share/Steam/compatibilitytools.d/GE-Proton-test'
            root.mkdir(parents=True); (root/'proton').touch()
            env={'HOME':tmp,'PROTONPATH':'GE-Proton'}
            self.assertEqual(prep.pin_environment(env,['/opt/umu/umu-run'])['PROTONPATH'],str(root))

    def test_standard_wine_environment_is_not_replaced_with_proton(self):
        self.assertEqual(prep.pin_environment({},['/usr/bin/wine']),{})
