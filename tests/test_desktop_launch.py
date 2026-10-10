import importlib.util
import json
import io
import os
import time
from contextlib import redirect_stdout
import tempfile
import subprocess
from pathlib import Path
import sys
import unittest
from unittest.mock import ANY, patch

CLIENT = Path(__file__).resolve().parents[1] / 'src/client'
sys.path.insert(0, str(CLIENT))
spec = importlib.util.spec_from_file_location('desktop_launch', CLIENT / 'desktop_launch.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class DesktopLaunchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = patch.object(module.session_history, 'ROOT', Path(temporary.name)/'sessions')
        root.start(); self.addCleanup(root.stop)
        worker = patch.object(module.session_history, 'queue_refresh')
        worker.start(); self.addCleanup(worker.stop)

    def test_force_during_creation_preserves_late_identity_without_reviving_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            record = dict(job='a'*32, label='vastgame-123', game='fixture', force_shutdown=True,
                          instance_id=None, phase='Shutting down rig', finished=False)
            (folder/'job.json').write_text(json.dumps(record))
            changed = module.update_job(folder, instance_id='42', creation_requested=True,
                                        phase='Game running', success=True)
            self.assertEqual(changed['instance_id'], '42')
            self.assertTrue(changed['creation_requested'])
            self.assertTrue(changed['force_shutdown'])
            self.assertEqual(changed['phase'], 'Shutting down rig')
            self.assertNotIn('success', changed)
            stopped = module.update_job(folder, stopped=True, instance_id=None)
            self.assertEqual(module.update_job(folder, instance_id='42', phase='Game running'), stopped)

    def test_session_clock_persists_play_time_and_survives_failed_stop_and_connect(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary); job = 'a' * 32; started = int(time.time() * 1000) - 12000
            with patch.object(module, 'STATE', state), patch.object(module, 'prune_jobs'), patch.object(module, 'run', return_value=(1, False)), patch.object(module, 'emit'):
                module.launch(job, 'fixture', '1', '0.2', '0', str(started))
            folder = state / job
            module.update_job(folder, instance_id='42', finished=True)
            with patch.object(module, 'STATE', state), patch.object(module, 'run', return_value=(1, False)), patch.object(module, 'interrupt_worker'), patch.object(module, 'alive', return_value=False), patch.object(module, 'emit'):
                module.stop(job)
                module.connect(job)
            record = json.loads((folder / 'job.json').read_text())
            self.assertEqual(record['started_at'], started)
            self.assertNotIn('ended_at', record)
            with patch.object(module, 'STATE', state), patch('game_catalog.library_summary', return_value={'games': []}), patch.object(module, 'guest_state', return_value=None), patch.object(module.subprocess, 'run') as lookup:
                lookup.return_value.returncode = 0
                lookup.return_value.stdout = json.dumps([dict(id=42, label=record['label'])])
                restored = module.current(job)
            self.assertEqual(restored['startedAt'], started)
            self.assertEqual(restored['endedAt'], 0)
            with patch.object(module, 'STATE', state), patch.object(module, 'run', return_value=(0, False)), patch.object(module, 'interrupt_worker'), patch.object(module, 'emit'):
                module.stop(job, force=True)
            record = json.loads((folder / 'job.json').read_text())
            self.assertTrue(record['stopped'])
            self.assertGreaterEqual(record['ended_at'], started)
            self.assertEqual(module.update_job(folder, ended_at=0), record)

    def test_session_clock_rejects_invalid_time_before_creating_job(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(module, 'STATE', Path(temporary)), patch.object(module, 'run') as run:
            for started in ('-1', '0', 'nan', str(int(time.time() * 1000) + 120000)):
                with self.assertRaises(ValueError): module.launch('a' * 32, 'fixture', '1', '0.2', '0', started)
            self.assertFalse(list(Path(temporary).iterdir()))
            run.assert_not_called()

    def test_exact_connect_waits_for_guest_preparation_before_streaming(self):
        root = CLIENT.parents[1]
        source = (root/'src/manager/commands.sh').read_text()
        function = source[source.index('connect_game() {'):source.index('\nshow_logs()')]
        with tempfile.TemporaryDirectory() as temporary:
            code = r''' 
instance_json() { printf '%s\n' '{"id":42,"label":"vastgame-123"}'; }
session_event() { :; }
wait_for_gaming() { printf 'WAIT_FOR_GAME_RUNTIME_SAVES %s\n' "$1"; }
launch_moonlight() { echo STREAM_OPENED_TOO_EARLY; return 99; }
get_vast_ip() { echo 100.76.110.5; }
die() { echo "$*" >&2; return 1; }
''' + function + '\nconnect_game 42 vastgame-123'
            result = subprocess.run(['bash', '-Eeuo', 'pipefail', '-c', code],
                env=dict(os.environ, INSTANCE_FILE=str(Path(temporary)/'instance')), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), 'WAIT_FOR_GAME_RUNTIME_SAVES 42')
            self.assertEqual((Path(temporary)/'instance').read_text().strip(), '42')
            wrong = subprocess.run(['bash', '-Eeuo', 'pipefail', '-c', code.replace('connect_game 42 vastgame-123', 'connect_game 42 vastgame-999')],
                env=dict(os.environ, INSTANCE_FILE=str(Path(temporary)/'instance')), capture_output=True, text=True)
            self.assertNotEqual(wrong.returncode, 0)
            self.assertNotIn('WAIT_FOR_GAME', wrong.stdout)

    def test_connect_uses_only_the_stored_vm_and_preserves_it_after_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary); job = 'a' * 32; folder = state / job; folder.mkdir()
            record = dict(job=job, instance_id='42', label='vastgame-123', finished=True, game_running=True)
            path = folder / 'job.json'; path.write_text(json.dumps(record))
            with patch.object(module, 'STATE', state), patch.object(module, 'alive', return_value=False), patch.object(module, 'run', return_value=(1, False)) as run, patch.object(module, 'emit') as emit:
                module.connect(job)
                run.assert_called_once_with(['connect', '--instance-id', '42', '--label', 'vastgame-123'], folder, record)
                emit.assert_called_with('finished', ok=False, phase='Connection failed; VM retained', instance_id='42', game_running=True)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['instance_id'], '42')
            self.assertFalse(saved['success'])

    def test_connect_after_game_exit_records_a_successful_restart_on_the_same_vm(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary); job = 'a' * 32; folder = state / job; folder.mkdir()
            record = dict(job=job, instance_id='42', label='vastgame-123', finished=True, success=False, game_running=False)
            path = folder / 'job.json'; path.write_text(json.dumps(record))
            def restarted(args, target, live):
                self.assertEqual(args, ['connect', '--instance-id', '42', '--label', 'vastgame-123'])
                live.update(module.update_job(target, game_running=True))
                return 0, False
            with patch.object(module, 'STATE', state), patch.object(module, 'alive', return_value=False), patch.object(module, 'run', side_effect=restarted), patch.object(module, 'emit'):
                module.connect(job)
            saved = json.loads(path.read_text())
            self.assertEqual(saved['instance_id'], '42')
            self.assertTrue(saved['success'])
            self.assertTrue(saved['game_running'])

    def test_connect_refuses_a_stopped_or_mismatched_job_without_spawning(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary); job = 'a' * 32; folder = state / job; folder.mkdir()
            for extra in (dict(stopped=True), dict(job='b' * 32)):
                record = dict(job=job, instance_id='42', label='vastgame-123', finished=True)
                record.update(extra)
                (folder / 'job.json').write_text(json.dumps(record))
                with patch.object(module, 'STATE', state), patch.object(module, 'run') as run:
                    with self.assertRaisesRegex(ValueError, 'VM identity'): module.connect(job)
                    run.assert_not_called()

    def test_job_updates_preserve_other_writers_and_cannot_revive_a_stopped_vm(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            path = folder / 'job.json'
            path.write_text(json.dumps(dict(job='a' * 32, instance_id='42', game_requested=False)))
            module.update_job(folder, game_requested=True)
            record = module.update_job(folder, phase='Starting game')
            self.assertTrue(record['game_requested'])
            stopped = module.update_job(folder, stopped=True, instance_id=None, success=True, phase='Rig shut down')
            self.assertEqual(module.update_job(folder, instance_id='42', success=False, phase='Launch failed'), stopped)
            self.assertEqual(json.loads(path.read_text()), stopped)

    def test_broken_library_metadata_does_not_hide_a_retained_vm(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            folder = state / ('a' * 32)
            folder.mkdir()
            (folder / 'job.json').write_text(json.dumps(dict(job='a' * 32, game='fixture',
                instance_id='42', label='vastgame-123', finished=True, success=False)))
            with patch.object(module, 'STATE', state), patch('game_catalog.library_summary', side_effect=ValueError('Invalid metadata')), \
                    patch.object(module.subprocess, 'run') as lookup:
                lookup.return_value.returncode = 0
                lookup.return_value.stdout = '[{"id":42,"label":"vastgame-123"}]'
                session = module.current()
            self.assertEqual(session['instanceId'], '42')
            self.assertEqual(session['gameName'], 'Game')

    def test_unknown_creation_recovers_only_its_exact_persisted_label(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary); job = 'a' * 32; folder = state/job; folder.mkdir()
            (folder/'job.json').write_text(json.dumps(dict(job=job, game='fixture', label='vastgame-123', instance_id=None, finished=True)))
            with patch.object(module, 'STATE', state), patch('game_catalog.library_summary', return_value={'games':[]}), \
                    patch.object(module, 'guest_state', return_value=None), patch.object(module.subprocess, 'run') as lookup:
                lookup.return_value.returncode = 0
                lookup.return_value.stdout = '[{"id":9,"label":"vastgame-999"},{"id":42,"label":"vastgame-123"}]'
                session = module.current()
            self.assertEqual(session['instanceId'], '42')
            self.assertEqual(json.loads((folder/'job.json').read_text())['instance_id'], '42')

    def test_retained_rental_lookup_failure_is_not_an_empty_account(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary); folder = state/('a' * 32); folder.mkdir()
            (folder/'job.json').write_text('{"job":"' + 'a'*32 + '"}')
            with patch.object(module, 'STATE', state), patch('game_catalog.library_summary', return_value={'games':[]}), \
                    patch.object(module.subprocess, 'run') as lookup:
                lookup.return_value.returncode = 1
                with self.assertRaisesRegex(ValueError, 'Cannot verify'): module.current()

    def test_retention_never_deletes_an_unresolved_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            for digit, stopped in [('a', True), ('b', False)]:
                folder = state/(digit * 32); folder.mkdir()
                path = folder/'job.json'; path.write_text(json.dumps(dict(stopped=stopped)))
                os.utime(path, (time.time()-40*86400, time.time()-40*86400))
            with patch.object(module, 'STATE', state): module.prune_jobs()
            self.assertFalse((state/('a'*32)).exists())
            self.assertTrue((state/('b'*32)).exists())

    @unittest.skipUnless(sys.platform == 'linux', 'The backend runs in Linux or WSL')
    def test_dead_worker_does_not_leave_the_reopened_watcher_waiting(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary); job = 'a'*32; folder = state/job; folder.mkdir()
            (folder/'job.json').write_text(json.dumps(dict(job=job, instance_id='42', phase='Booting rig')))
            output = io.StringIO()
            with patch.object(module, 'STATE', state), redirect_stdout(output): module.watch(job)
            events = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertFalse(events[-1]['ok'])
            self.assertEqual(events[-1]['instance_id'], '42')

    def test_invalid_arguments_cannot_spawn_a_process(self):
        with patch.object(module.subprocess, 'Popen', side_effect=AssertionError('Must not run')):
            for game, offer, price in (('../private', '1', '1'), ('game', '0', '1'), ('game', '1', 'nan'), ('game', '1', '-1')):
                with self.assertRaises(ValueError): module.launch('a' * 32, game, offer, price)

    def test_credentials_and_signed_urls_are_not_ui_logs(self):
        clean = module.redact('api_key=secret tskey-auth-123 https://example.com/?token=private')
        self.assertNotIn('=secret', clean)
        self.assertNotIn('tskey-auth', clean)
        self.assertNotIn('https://example.com', clean)

    def test_phases_come_from_engine_events(self):
        self.assertEqual(module.phase('VASTGAME | DRIVE | restoring'), 'Restoring game and saves')
        self.assertIsNone(module.phase('unrelated diagnostic line'))
        self.assertEqual(module.phase('✓ Game process detected. Use vastgame logs game for diagnostics.'), 'Game running')
        self.assertNotEqual(module.phase('CLOUD GAMING READY'), 'Game running')

    def test_shutdown_refuses_a_different_job_before_any_process_action(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            job = 'a' * 32
            (state / job).mkdir()
            (state / job / 'job.json').write_text(json.dumps(dict(job='b' * 32, instance_id='42', label='vastgame-123')))
            with patch.object(module, 'STATE', state), patch.object(module, 'run') as run, patch.object(module.os, 'kill') as kill:
                with self.assertRaisesRegex(ValueError, 'VM identity'):
                    module.stop(job)
                run.assert_not_called()
                kill.assert_not_called()

    def test_shutdown_uses_exact_instance_and_preserves_it_after_backup_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            job = 'a' * 32
            folder = state / job
            folder.mkdir()
            (folder / 'job.json').write_text(json.dumps(dict(job=job, instance_id='42', label='vastgame-123', pid=12, birth='old')))
            with patch.object(module, 'STATE', state), patch.object(module, 'birth', return_value='new'), patch.object(module, 'run', return_value=(1, False)) as run, patch.object(module.os, 'kill') as kill, patch.object(module, 'emit') as emit:
                module.stop(job)
                kill.assert_not_called()
                run.assert_called_once_with(['stop', '--instance-id', '42', '--label', 'vastgame-123', '--startup-job', job], folder)
                emit.assert_called_with('finished', ok=False, phase='Shutdown failed; VM retained', instance_id='42')

    def test_second_shutdown_forces_exact_vm_and_cannot_be_revived_by_old_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary); job = 'a'*32; folder = state/job; folder.mkdir()
            path = folder/'job.json'
            path.write_text(json.dumps(dict(job=job, game='fixture', instance_id='42', label='vastgame-123')))
            def run(args, target):
                self.assertEqual(target, folder)
                if '--force' in args:
                    self.assertEqual(args, ['stop', '--force', '--instance-id', '42', '--label', 'vastgame-123'])
                    return 0, False
                module.stop(job, force=True)
                return 1, True
            with patch.object(module, 'STATE', state), patch.object(module, 'interrupt_worker') as interrupt, patch.object(module, 'run', side_effect=run), patch.object(module, 'emit') as emit:
                module.stop(job)
                interrupt.assert_any_call(ANY, job, 'stop_', 'stop')
                completions = [call for call in emit.call_args_list if call.args[0] == 'finished']
                self.assertEqual(len(completions), 1)
                self.assertTrue(completions[0].kwargs['ok'])
            record = json.loads(path.read_text())
            self.assertTrue(record['stopped'])
            self.assertIsNone(record['instance_id'])
            self.assertTrue(record['shutdown_requested'])
            self.assertTrue(record['force_shutdown'])
            self.assertIsNone(module.update_job(folder, instance_id='42', success=False, phase='Late failure')['instance_id'])

    def test_failed_normal_shutdown_persists_force_choice_for_reopening(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary); job = 'a'*32; folder = state/job; folder.mkdir()
            path = folder/'job.json'
            path.write_text(json.dumps(dict(job=job, instance_id='42', label='vastgame-123')))
            with patch.object(module, 'STATE', state), patch.object(module, 'interrupt_worker'), patch.object(module, 'run', return_value=(1, False)), patch.object(module, 'emit'):
                module.stop(job)
            record = json.loads(path.read_text())
            self.assertEqual(record['instance_id'], '42')
            self.assertTrue(record['shutdown_requested'])
            self.assertEqual(record['phase'], 'Shutdown failed; VM retained')

    def test_force_shutdown_interrupts_reconnect_and_late_completion_cannot_revive_rig(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary); job = 'a'*32; folder = state/job; folder.mkdir()
            path = folder/'job.json'
            path.write_text(json.dumps(dict(job=job, instance_id='42', label='vastgame-123', finished=True)))
            def run(args, current_folder, record=None):
                if args[0] == 'connect':
                    saved = json.loads(path.read_text())
                    self.assertEqual(saved['pid'], os.getpid())
                    self.assertFalse(saved['finished'])
                    module.stop(job, force=True)
                    return 1, True
                self.assertEqual(args, ['stop', '--force', '--instance-id', '42', '--label', 'vastgame-123'])
                return 0, False
            with patch.object(module, 'STATE', state), patch.object(module, 'alive', return_value=False), \
                 patch.object(module, 'interrupt_worker') as interrupt, patch.object(module, 'run', side_effect=run), patch.object(module, 'emit'):
                module.connect(job)
                interrupt.assert_any_call(ANY, job, mode='connect')
            saved = json.loads(path.read_text())
            self.assertTrue(saved['stopped'])
            self.assertIsNone(saved['instance_id'])
            self.assertEqual(saved['phase'], 'Rig shut down')

    def test_reconnect_spawn_failure_finishes_operation_without_losing_vm_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary); job = 'a'*32; folder = state/job; folder.mkdir()
            path = folder/'job.json'
            path.write_text(json.dumps(dict(job=job, instance_id='42', label='vastgame-123', finished=True)))
            with patch.object(module, 'STATE', state), patch.object(module, 'alive', return_value=False), \
                 patch.object(module, 'run', side_effect=OSError('Cannot spawn backend')):
                with self.assertRaises(OSError): module.connect(job)
            saved = json.loads(path.read_text())
            self.assertTrue(saved['finished'])
            self.assertFalse(saved['success'])
            self.assertEqual(saved['instance_id'], '42')

    def test_force_worker_signal_pins_identity_and_rejects_pid_reuse_or_other_jobs(self):
        record = dict(stop_pid=12, stop_birth='expected')
        for births, command in ((['expected', 'reused'], b''), (['expected', 'expected'], b'python3\0/app/src/client/desktop_launch.py\0stop\0'+b'b'*32+b'\0')):
            with patch.object(module, 'birth', side_effect=births), patch.object(module.os, 'pidfd_open', return_value=99), patch.object(module.os, 'close'), patch.object(Path, 'read_bytes', return_value=command), patch.object(module.signal, 'pidfd_send_signal') as kill:
                module.interrupt_worker(record, 'a'*32, 'stop_', 'stop')
                kill.assert_not_called()
        with patch.object(module, 'birth', return_value='expected'), patch.object(module.os, 'pidfd_open', return_value=99), patch.object(module.os, 'close'), patch.object(Path, 'read_bytes', return_value=b'python3\0/app/src/client/desktop_launch.py\0stop\0'+b'a'*32+b'\0'), patch.object(module.signal, 'pidfd_send_signal') as kill:
            module.interrupt_worker(record, 'a'*32, 'stop_', 'stop')
            kill.assert_called_once_with(99, module.signal.SIGTERM)

    @unittest.skipUnless(sys.platform == 'linux', 'The backend runs in Linux or WSL')
    def test_reopened_completed_game_reports_running_without_exposing_private_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            job = 'a' * 32
            folder = state/job
            folder.mkdir()
            (folder/'job.json').write_text(json.dumps(dict(job=job, finished=True, success=True,
                instance_id='42', game_running=True, phase='Game ready', private='secret')))
            output = io.StringIO()
            with patch.object(module, 'STATE', state), redirect_stdout(output):
                module.watch(job)
            events = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertTrue(events[-1]['game_running'])
            self.assertEqual(events[-1]['type'], 'finished')
            self.assertEqual(events[-1]['instance_id'], '42')
            self.assertNotIn('secret', output.getvalue())
