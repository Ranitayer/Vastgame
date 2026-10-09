from support import cli_source
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/runtime'))
import game_state as state


class GameShutdownTests(unittest.TestCase):
    def test_only_game_executables_in_the_exact_prefix_are_shutdown_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            proc = Path(temporary)
            for pid, prefix, executable in [(1, 'fixture', 'Game.exe'), (2, 'other', 'Game.exe'), (3, 'fixture', 'services.exe'), (4, 'fixture', 'lutris'), (5, 'fixture', 'wineserver'), (6, 'other', 'wineserver')]:
                folder = proc / str(pid); folder.mkdir()
                (folder/'environ').write_bytes(f'WINEPREFIX=/prefixes/{prefix}\0'.encode())
                (folder/'cmdline').write_bytes(executable.encode())
                (folder/'comm').write_text(executable)
            self.assertEqual(state.wine_processes('fixture', proc), [1])
            self.assertEqual(state.wine_processes('fixture', proc, server=True), [5])

    def test_pid_identity_is_rechecked_before_a_graceful_signal(self):
        import signal
        for current, count in [([], 0), ([42], 1)]:
            with patch.object(state, 'wine_processes', side_effect=[[42], current]), patch.object(state.os, 'pidfd_open', return_value=7), patch.object(state.os, 'close') as close, patch.object(signal, 'pidfd_send_signal') as send:
                state.terminate_game('fixture')
                self.assertEqual(send.call_count, count)
                if count: send.assert_called_once_with(7, signal.SIGTERM)
                close.assert_called_once_with(7)

    def test_an_ignored_close_request_uses_scoped_termination_then_verifies_idle(self):
        busy = subprocess.CalledProcessError(1, 'idle')
        with patch.object(state, 'containers', return_value=['owned']), patch.object(state, 'container_state') as action, patch.object(state, 'idle', side_effect=[busy, None, None]) as idle, patch.object(state.time, 'monotonic', side_effect=[0, 21]), patch.object(state.time, 'sleep'):
            state.stop_cleanly('fixture')
            self.assertEqual([call.args[1] for call in action.call_args_list], ['close', 'terminate', 'flush'])
            self.assertEqual(idle.call_count, 3)

    def test_registry_flush_waits_for_the_matching_server_to_exit(self):
        with patch.object(state, 'container_idle') as idle, patch.object(state, 'terminate_game') as terminate, patch.object(state, 'wine_processes', side_effect=[[42], []]), patch.object(state.time, 'monotonic', return_value=0), patch.object(state.time, 'sleep'):
            state.flush_runtime('fixture')
            terminate.assert_called_once_with('fixture', server=True)
            self.assertEqual(idle.call_count, 2)

    def test_unconfirmed_registry_flush_blocks_backup(self):
        with patch.object(state, 'container_idle'), patch.object(state, 'terminate_game'), patch.object(state, 'wine_processes', return_value=[42]), patch.object(state.time, 'monotonic', side_effect=[0, 11]):
            with self.assertRaisesRegex(RuntimeError, 'registry flush did not finish'):
                state.flush_runtime('fixture')


class LocalRemote:
    """Filesystem object store; exercises the same commit/restore code."""
    def __init__(self, root): self.root = str(root); self.uploads = []; self.fail = False
    def list(self, path):
        p = Path(self.root) / path
        return sorted(c.name + '/' for c in p.iterdir() if c.is_dir())
    def run(self, *args, **kwargs):
        return '\n'.join(p.name for p in Path(args[1]).iterdir() if p.is_file())
    def read(self, path): return (Path(self.root) / path).read_text()
    def download(self, path, local): shutil.copyfile(Path(self.root) / path, local)
    def upload(self, local, path):
        if self.fail: raise RuntimeError('Network failed')
        dest = Path(self.root) / path; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local, dest); self.uploads.append(path)


class StateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'gaming'; self.root.mkdir()
        remote = Path(self.tmp.name) / 'remote'; remote.mkdir(); self.remote = LocalRemote(remote)
        self.m = dict(id='fixture', version='v1', state=dict(saves=[dict(base='prefix', path='drive_c/users/user/Documents/save.bin', required=True)], configs=[dict(base='game', path='config.ini', required=True)], shaders=[]))
        self.save = self.root / 'prefixes/fixture/drive_c/users/user/Documents/save.bin'
        self.save.parent.mkdir(parents=True); self.save.write_bytes(b'real save')
        self.config = self.root / 'games/fixture/config.ini'; self.config.parent.mkdir(parents=True); self.config.write_text('DLSS=off')
        self.shader = self.root / 'shaders/fixture/cache/pipeline.bin'; self.shader.parent.mkdir(parents=True); self.shader.write_bytes(b'compiled')

    def backup(self): return state.backup(self.m, self.root, self.remote, '123', 'a'*64)

    def test_gpu_probe_failure_keeps_backup_but_disables_shader_reuse(self):
        errors = (FileNotFoundError('nvidia-smi'), subprocess.CalledProcessError(1, 'nvidia-smi'), subprocess.TimeoutExpired('nvidia-smi', 20))
        for error in errors:
            with self.subTest(error=type(error).__name__), patch.object(state.subprocess, 'check_output', side_effect=error), patch.object(state, 'runner_builds', return_value={}):
                context = state.cache_context(self.m)
                self.assertIsNone(context['gpu_driver'])
                key = state.context_key(context)
                receipt = state.backup(self.m, self.root, self.remote, '123', key, context)
                self.assertEqual(len(receipt['artifacts']), 3)
                self.save.unlink(); self.config.unlink(); self.shader.unlink()
                state.restore(self.m, self.root, self.remote, key, context)
                self.assertEqual(self.save.read_bytes(), b'real save')
                self.assertEqual(self.config.read_text(), 'DLSS=off')
                self.assertFalse(self.shader.exists())
                self.shader.write_bytes(b'compiled')

    def test_round_trip_preserves_saves_config_shaders(self):
        receipt = self.backup(); self.save.unlink(); self.config.unlink(); self.shader.unlink()
        state.restore(self.m, self.root, self.remote, 'a'*64)
        self.assertEqual(self.save.read_bytes(), b'real save'); self.assertEqual(self.config.read_text(), 'DLSS=off')
        self.assertEqual(self.shader.read_bytes(), b'compiled')
        self.assertEqual(receipt['instance_id'], '123')

    def test_missing_required_save_blocks_commit(self):
        self.save.unlink()
        with self.assertRaisesRegex(ValueError, 'missing'): self.backup()
        self.assertEqual(self.remote.uploads, [])

    def test_empty_required_save_directory_blocks_commit(self):
        self.save.unlink(); self.m['state']['saves'][0]['path'] = 'drive_c/users/user/Documents'
        with self.assertRaisesRegex(ValueError, 'empty'): self.backup()

    def test_failed_upload_preserves_previous_revision(self):
        original = self.backup(); self.save.write_bytes(b'new save'); self.remote.fail = True
        with self.assertRaises(RuntimeError): self.backup()
        self.assertEqual(state.latest(self.remote, 'fixture')['snapshot'], original['snapshot'])

    def test_unchanged_files_reuse_objects(self):
        self.backup(); self.remote.uploads.clear(); self.backup()
        self.assertEqual(len(self.remote.uploads), 1); self.assertTrue(self.remote.uploads[0].endswith('COMMITTED.json'))

    def test_corruption_blocks_restore_before_live_writes(self):
        r = self.backup(); (Path(self.remote.root) / r['artifacts'][1]['path']).write_bytes(b'bad')
        self.save.write_bytes(b'leave current save')
        with self.assertRaises(ValueError): state.restore(self.m, self.root, self.remote, 'a'*64)
        self.assertEqual(self.save.read_bytes(), b'leave current save')

    def test_partial_snapshot_skipped(self):
        r = self.backup()
        (Path(self.remote.root) / 'state/fixture/snapshots'/('9'*20+'-'+'a'*32)).mkdir()
        self.assertEqual(state.latest(self.remote, 'fixture')['snapshot'], r['snapshot'])

    def test_incompatible_shaders_skipped_saves_restored(self):
        self.backup(); self.save.unlink(); self.shader.unlink()
        state.restore(self.m, self.root, self.remote, 'b'*64)
        self.assertTrue(self.save.exists()); self.assertFalse(self.shader.exists())

    def test_path_and_symlink_escape_rejected(self):
        self.m['state']['saves'][0]['path'] = '../escape'
        with self.assertRaises(ValueError): self.backup()
        self.m['state']['saves'][0]['path'] = 'evil/save.bin'
        (self.root/'prefixes/fixture/evil').symlink_to(self.save.parent)
        # Outside this game's prefix, even if inside another gaming directory.
        (self.root/'prefixes/fixture/evil').unlink()
        (self.root/'prefixes/fixture/evil').symlink_to(self.root/'games/fixture')
        with self.assertRaises(ValueError): self.backup()

    def test_tar_traversal_and_links_rejected(self):
        for name, type_ in [('../escape', tarfile.REGTYPE), ('prefix/link', tarfile.SYMTYPE)]:
            archive = Path(self.tmp.name) / 'malicious.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                info = tarfile.TarInfo(name); info.type = type_; tar.addfile(info)
            artifact = dict(sha256=state.digest(archive), files={name:dict(size=0, sha256='0'*64)})
            with self.assertRaises(ValueError): state.unpack(artifact, archive, Path(self.tmp.name)/'stage')

    def test_driver_dlls_never_backed_up(self):
        dll = self.save.parent/'nvngx.dll'; dll.write_bytes(b'driver')
        with self.assertRaisesRegex(ValueError, 'Driver-specific'): self.backup()

    def test_no_state_returns_fresh_without_remote_errors_hidden(self):
        self.assertIsNone(state.restore(self.m, self.root, self.remote, 'a'*64))
        with patch.object(self.remote, 'list', side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError): state.restore(self.m, self.root, self.remote, 'a'*64)

    def test_empty_manifest_cannot_silently_destroy_save_data(self):
        shutil.rmtree(self.root/'prefixes'); self.m['state']['saves'] = []
        with self.assertRaisesRegex(ValueError, 'No save'): self.backup()

    def test_real_rclone_transport_round_trip(self):
        remote_root = Path(self.tmp.name)/'rclone-remote'; remote_root.mkdir()
        remote = state.Remote(str(remote_root))
        state.backup(self.m, self.root, remote, '123', 'a'*64)
        self.save.unlink()
        state.restore(self.m, self.root, remote, 'a'*64)
        self.assertEqual(self.save.read_bytes(), b'real save')


if __name__ == '__main__': unittest.main()

class StopTests(unittest.TestCase):
    def test_failed_final_backup_never_requests_destruction(self):
        import subprocess
        cli = cli_source()
        fn = cli[cli.index('stop_game() {'):cli.index('\n# ============================================================\n# GAME CATALOG', cli.index('stop_game() {'))]
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp)/'destroy'
            code = "pick_instance() { echo 123; }; safe_backup() { return 1; }; warn() { :; }; ok() { :; }; vastai() { echo destroyed > \"$DESTROY_LOG\"; }; " + fn + '\nstop_game'
            import os
            r = subprocess.run(['bash','-c',code], env=dict(os.environ,DESTROY_LOG=str(log)), capture_output=True)
            self.assertEqual(r.returncode, 1); self.assertFalse(log.exists())

    def test_retry_after_first_interrupted_upload(self):
        fixture = StateTests(); fixture.setUp()
        try:
            (Path(fixture.remote.root)/'state/fixture/objects').mkdir(parents=True)
            receipt = fixture.backup()
            self.assertEqual(state.latest(fixture.remote, 'fixture')['snapshot'], receipt['snapshot'])
        finally:
            fixture.tmp.cleanup()

class DeferredShaderTests(unittest.TestCase):
    setUp = StateTests.setUp
    backup = StateTests.backup
    def fixture_context(self, builds):
        return dict(gpu_driver='RTX test, 580', runner={'version':'ge-proton'}, builds=builds, schema=1, package=[], game_version='v1')

    def stage_pending(self):
        builds={'wine':['ge-1'], 'proton':[]}
        context=self.fixture_context(builds)
        state.backup(self.m,self.root,self.remote,'123',state.context_key(context),context)
        self.shader.unlink()
        cold=self.fixture_context({'wine':[], 'proton':[]})
        state.restore(self.m,self.root,self.remote,state.context_key(cold),cold,defer_shaders=True)
        (self.root/'profiles/fixture/cache-context.json').write_text(json.dumps(cold))
        return builds

    def container_path(self, value, *args):
        if str(value) in ['/profiles','/games','/prefixes','/saves','/configs','/shaders']:
            return Path(self.root/str(value).lstrip('/'),*args)
        return Path(value,*args)

    def test_shader_restore_waits_for_matching_downloaded_runner(self):
        builds=self.stage_pending()
        self.assertFalse(self.shader.exists())
        with patch.object(state,'Path',side_effect=self.container_path), patch.object(state,'runner_builds',return_value=builds):
            state.prepare_shaders('fixture')
        self.assertEqual(self.shader.read_bytes(),b'compiled')

    def test_changed_runner_never_receives_previous_compiled_cache(self):
        self.stage_pending()
        with patch.object(state,'Path',side_effect=self.container_path), patch.object(state,'runner_builds',return_value={'wine':['ge-2'],'proton':[]}):
            state.prepare_shaders('fixture')
        self.assertFalse(self.shader.exists())

    def test_corrupt_pending_cache_fails_before_wine_launch(self):
        builds=self.stage_pending()
        (self.root/'profiles/fixture/pending-shaders/shaders/cache/pipeline.bin').write_bytes(b'corrupt')
        with patch.object(state,'Path',side_effect=self.container_path), patch.object(state,'runner_builds',return_value=builds):
            with self.assertRaisesRegex(ValueError,'checksum'):
                state.prepare_shaders('fixture')
