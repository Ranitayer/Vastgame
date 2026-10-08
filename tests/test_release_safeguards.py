import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import test_game_state as state_tests
state = state_tests.state

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('package_publish', ROOT/'src/client/package_publish.py')
package = importlib.util.module_from_spec(spec); spec.loader.exec_module(package)


class SaveSafeguardsTests(unittest.TestCase):
    setUp = state_tests.StateTests.setUp
    backup = state_tests.StateTests.backup
    def test_registry_user_data_restores_without_prefix_binaries(self):
        reg = self.root/'prefixes/fixture/user.reg'; reg.write_bytes(b'WINE REGISTRY Version 2\nsettings')
        record = self.backup()
        self.assertIn('prefix/user.reg', record['artifacts'][1]['files'])
        reg.unlink(); state.restore(self.m, self.root, self.remote, 'a'*64)
        self.assertEqual(reg.read_bytes(), b'WINE REGISTRY Version 2\nsettings')

    def test_unknown_coverage_cannot_commit_even_with_generic_user_files(self):
        self.m['state']['saves'] = []
        with self.assertRaisesRegex(ValueError, 'coverage'):
            self.backup()
        self.assertEqual(self.remote.uploads, [])

    def test_unsupported_store_paths_cannot_be_silently_skipped(self):
        self.m['state']['saves'] = []
        self.m['state']['discovery'] = dict(unsupported=['<root>/userdata/<storeUserId>'], recipes=[])
        with self.assertRaisesRegex(ValueError, 'coverage incomplete'):
            self.backup()

    def test_live_checkpoint_does_not_stop_or_require_idle_game(self):
        profile = self.root/'profiles/fixture'; profile.mkdir(parents=True)
        (profile/'manifest.json').write_text(json.dumps(self.m))
        with patch('sys.argv', ['game_state.py','backup','fixture','--root',str(self.root),'--live','--cache-key','a'*64]), \
             patch.object(state, 'Remote', return_value=self.remote), patch.object(state, 'stop_cleanly') as stop, \
             patch.object(state, 'idle') as idle:
            state.main()
        stop.assert_not_called(); idle.assert_not_called()
        self.assertIsNotNone(state.latest(self.remote, 'fixture'))

    def test_live_checkpoint_reuses_compiled_shader_object(self):
        original = self.backup()
        checkpoint = state.backup(self.m, self.root, self.remote, '123', 'a'*64, live=True)
        self.assertEqual(checkpoint['artifacts'][2], original['artifacts'][2])


    def test_changing_shader_cache_does_not_block_save_checkpoint(self):
        original = self.backup()
        original_archive = state.archive
        def archive(files, target):
            if target.name == 'shaders.tar.gz':
                raise ValueError('Shader cache changed during capture')
            return original_archive(files, target)
        self.save.write_bytes(b'new progress')
        with patch.object(state, 'archive', side_effect=archive):
            checkpoint = state.backup(self.m, self.root, self.remote, '123', 'a'*64, live=True)
        self.assertEqual(checkpoint['artifacts'][2], original['artifacts'][2])
        self.assertNotEqual(checkpoint['artifacts'][0]['files'], original['artifacts'][0]['files'])



class LifecycleSafeguardsTests(unittest.TestCase):
    def shell(self, script):
        return subprocess.run(['bash','-euc',script], capture_output=True, text=True)

    def test_routes_only_to_exact_instance_launch_label(self):
        output = self.shell(f'''source "{ROOT}/src/manager/network.sh"
STATUS_PORT=48199
instance_json() {{ echo '{{"id":123,"label":"vastgame-123"}}'; }}
tailscale() {{ echo '{{"Peer":{{"a":{{"Online":true,"HostName":"vast-gaming","TailscaleIPs":["100.64.0.1"]}},"b":{{"Online":true,"HostName":"vast-gaming-2","TailscaleIPs":["100.64.0.2"]}}}}}}'; }}
curl() {{ if [[ "$*" == *100.64.0.1* ]]; then echo vastgame-999; else echo vastgame-123; fi; }}
get_vast_ip 123
''')
        self.assertEqual(output.returncode,0,output.stderr)
        self.assertEqual(output.stdout.strip(),'100.64.0.2')

    def test_destroy_is_not_confirmed_while_instance_still_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp)/'instance'; file.write_text('123')
            result = self.shell(f'''source "{ROOT}/src/manager/provider.sh"
INSTANCE_FILE="{file}"
instance_json() {{ echo '{{"id":123,"label":"vastgame-123"}}'; }}
vastai() {{ if [[ "$1" == show ]]; then echo '[{{"id":123}}]'; fi; }}
sleep() {{ :; }}
warn() {{ :; }}
destroy_verified 123
''')
            self.assertNotEqual(result.returncode,0)
            self.assertTrue(file.exists())

    def test_dispatch_lock_prevents_second_mutation(self):
        dispatcher = (ROOT/'src/manager/commands.sh').read_text().split('# Normalize long',1)[1]
        with tempfile.TemporaryDirectory() as tmp:
            import fcntl
            with (Path(tmp)/'lifecycle.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                result = self.shell(f'STATEDIR="{tmp}"; die() {{ echo "$*"; exit 1; }}; command=backup; '+ '# Normalize long'+dispatcher)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('Another Vastgame operation',result.stdout)

    def test_ingest_does_not_take_lifecycle_lock(self):
        dispatcher = (ROOT/'src/manager/commands.sh').read_text().split('# Normalize long',1)[1]
        with tempfile.TemporaryDirectory() as tmp:
            import fcntl
            with (Path(tmp)/'lifecycle.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                result=self.shell(f'STATEDIR="{tmp}"; die() {{ echo "$*"; exit 1; }}; game_ingest() {{ echo imported; }}; set -- ingest url fixture; '+'# Normalize long'+dispatcher)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('imported',result.stdout)

    def test_ingest_respects_catalog_writer_lock(self):
        dispatcher = (ROOT/'src/manager/commands.sh').read_text().split('# Normalize long',1)[1]
        with tempfile.TemporaryDirectory() as tmp:
            import fcntl
            with (Path(tmp)/'catalog.lock').open('a') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                result=self.shell(f'STATEDIR="{tmp}"; die() {{ echo "$*"; exit 1; }}; game_ingest() {{ echo imported; }}; set -- ingest url fixture; '+'# Normalize long'+dispatcher)
            self.assertNotEqual(result.returncode,0)
            self.assertIn('catalog operation',result.stdout)
            self.assertNotIn('imported',result.stdout)

    def test_disk_peak_accounts_for_bounded_parts_not_full_archive(self):
        source = (ROOT/'src/manager/catalog.sh').read_text()
        function = source[source.index('calculate_disk_requirement() {'):source.index('\nvalid_game_id()')]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'selected').write_text('fixture')
            manifest=root/'manifest'; manifest.write_text(json.dumps(dict(package=dict(size=40*10**9,unpacked_bytes=45*10**9,parts=[dict(size=256*1024**2)]*150))))
            result=self.shell(f'SELECTED_GAME_FILE="{root}/selected"; valid_game_id() {{ :; }}; game_manifest() {{ echo "{manifest}"; }}; die() {{ exit 1; }}; '+function+'\ncalculate_disk_requirement; echo "$DISK_GB"')
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertGreaterEqual(int(result.stdout),90)
            self.assertLess(int(result.stdout),100)


class ImmutablePackageTests(unittest.TestCase):
    def fixture(self, root):
        source=root/'source'; source.mkdir()
        (source/'Game.exe').write_bytes(b'MZ'+bytes(58)+(64).to_bytes(4, 'little')+b'PE\0\0')
        manifest=root/'manifest.json'
        from game_catalog import create
        manifest.write_text(json.dumps(create(source, 'fixture')))
        return source, manifest

    def stream(self, source, work, digest):
        data=(source/'Game.exe').read_bytes()
        digest.update(data)
        part=work/'part-00000'; part.write_bytes(data)
        yield part, dict(name=part.name, size=len(data), sha256=package.hash_file(part)), package.hash_file(part, 'md5')

    def test_bad_remote_hash_never_replaces_previous_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source, manifest=self.fixture(root); original=manifest.read_text()
            with patch.object(package, 'compressed_parts', side_effect=self.stream), \
                 patch.object(package, 'prepare_upload_folder'), \
                 patch.object(package, 'copy_part'), patch.object(package, 'remote_md5', return_value='bad'):
                with self.assertRaisesRegex(ValueError, 'verification failed'):
                    package.publish(manifest, source, root/'work')
            self.assertEqual(manifest.read_text(), original)

    def test_successful_publications_keep_old_content_and_commit_manifest_last(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source, manifest=self.fixture(root); remote=root/'remote'; calls=[]
            def target(value): return remote/value.split(':',1)[1]
            def run(args, **kwargs):
                calls.append(args[3]); dest=target(args[3]); dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(args[2],dest)
            def output(args, **kwargs):
                if args[1] == 'hashsum':
                    p=target(args[3]); return package.hash_file(p,'md5')+'  '+p.name+'\n'
                return target(args[2]).read_bytes()
            with patch.object(package,'compressed_parts',side_effect=self.stream), \
                 patch.object(package,'prepare_upload_folder'), \
                 patch.object(package,'copy_part',side_effect=lambda args, *ignored: run(args)), \
                 patch.object(package.subprocess,'run',side_effect=run), \
                 patch.object(package.subprocess,'check_output',side_effect=output):
                for content in (b'first', b'second'):
                    with (source/'Game.exe').open('ab') as file: file.write(content)
                    package.publish(manifest,source,root/'work')
                    self.assertIn('/manifests/',calls[-1])
            versions=[p for p in (remote/'VastGaming/games/fixture').iterdir() if len(p.name)==64]
            self.assertEqual(len(versions),2)
            self.assertTrue(all((p/'COMMITTED.json').is_file() for p in versions))
            self.assertEqual(len(list((remote/'VastGaming/games/fixture/objects').iterdir())),2)

    def test_upload_folder_is_created_before_parallel_parts(self):
        events = []
        def listing(args, **kwargs):
            events.append('list')
            name = 'fixture' if args[2].endswith('/games') else 'objects'
            return json.dumps([dict(Name=name, IsDir=True)])
        with patch.object(package.subprocess, 'run', side_effect=lambda *a, **k: events.append('mkdir')), \
             patch.object(package.subprocess, 'check_output', side_effect=listing):
            package.prepare_upload_folder('remote:root', 'fixture')
        self.assertEqual(events, ['mkdir', 'list', 'list'])

    def test_duplicate_game_folders_fail_before_packaging(self):
        with patch.object(package.subprocess, 'run'), \
             patch.object(package.subprocess, 'check_output', return_value=json.dumps(
                 [dict(Name='fixture'), dict(Name='fixture')])):
            with self.assertRaisesRegex(ValueError, 'ambiguous'):
                package.prepare_upload_folder('remote:root', 'fixture')

    def test_retry_receipt_still_checks_remote_hash_without_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'part-00000'; path.write_bytes(b'bytes')
            part=dict(name=path.name, sha256=package.hash_file(path), object='games/fixture/objects/hash.part')
            md5=package.hash_file(path,'md5')
            with patch.object(package.subprocess,'run') as upload, patch.object(package,'remote_md5',return_value=md5) as verify:
                package.upload_part(path,part,md5,'remote',dict(part,md5=md5))
                upload.assert_not_called(); verify.assert_called_once()

    def test_real_rclone_publication_retry_is_idempotent(self):
        import shutil
        if not all(shutil.which(command) for command in ('rclone', 'tar', 'zstd')):
            self.skipTest('rclone, tar and zstd required for local transport verification')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source, manifest=self.fixture(root)
            for content in (b'', b'', b'updated'):
                with (source/'Game.exe').open('ab') as file: file.write(content)
                package.publish(manifest,source,root/'work',remote=str(root/'remote'))
            versions=[p for p in (root/'remote/games/fixture').iterdir() if len(p.name)==64]
            self.assertEqual(len(versions),2)
            self.assertEqual(json.loads(manifest.read_text())['version'],'v1')
