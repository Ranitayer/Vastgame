"""Offline session durability, identity and billing reconciliation checks."""
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import subprocess
import os
import pty
import errno
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT/'src/client'))
import session_history as history

spec = importlib.util.spec_from_file_location('vast_session_charges', PROJECT/'src/providers/vast/charges.py')
charges = importlib.util.module_from_spec(spec)
spec.loader.exec_module(charges)


class HistoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)/'sessions'
        root = patch.object(history, 'ROOT', self.root)
        root.start(); self.addCleanup(root.stop)
        worker = patch.object(history, 'queue_refresh')
        self.worker = worker.start(); self.addCleanup(worker.stop)
        self.label = 'vastgame-1700000000000000000'

    def test_rental_ids_are_reserved_even_when_the_clock_collides(self):
        with patch.object(history.time, 'time_ns', return_value=1700000000000000000):
            first, second = history.new_label(), history.new_label()
        self.assertEqual(first, self.label)
        self.assertNotEqual(first, second)
        history.begin(first, 'first-game'); history.begin(second, 'second-game')
        self.assertEqual(history.read(first)['game_id'], 'first-game')
        self.assertEqual(history.read(second)['game_id'], 'second-game')

    def test_guest_startup_stages_are_recorded_without_console_output(self):
        history.begin(self.label, 'fixture')
        job = dict(label=self.label, game='fixture', phase='Booting rig', finished=False)
        with patch.object(history, 'milliseconds', return_value=1700000001000):
            history.job_update(dict(job, progress=dict(active='game')))
        with patch.object(history, 'milliseconds', return_value=1700000002000):
            history.job_update(dict(job, progress=dict(active='game')))
            history.job_update(dict(job, progress=dict(active='saves')))
        stages = history.read(self.label)['stage_times']
        self.assertEqual(stages['Restoring game'], 1700000001000)
        self.assertEqual(stages['Restoring saves'], 1700000002000)
        self.assertFalse((history.folder(self.label)/'logs.jsonl.gz').exists())
        history.update(self.label, outcome='stopped', ended_at=1700000003000)
        history.job_update(dict(job, progress=dict(active='runtime')))
        self.assertEqual(history.read(self.label)['stage_times'], stages)

    def test_stage_archive_keeps_repeated_reconnect_transitions_separate_from_logs(self):
        history.begin(self.label, 'fixture')
        for index, name in enumerate(['Booting rig', 'Game running', 'Booting rig']):
            with patch.object(history, 'milliseconds', return_value=1700000001000+index):
                history.update(self.label, phase=name)
        page = history.log_page(self.label, limit=2, events=True)
        self.assertEqual([item['message'] for item in page['entries']], ['Booting rig', 'Game running'])
        tail = history.log_page(self.label, page['next_cursor'], events=True)
        self.assertEqual([item['message'] for item in tail['entries']], ['Booting rig'])
        self.assertTrue(tail['events_complete'])
        logs = history.log_page(self.label)
        self.assertEqual(logs['entries'], [])
        self.assertEqual(len(logs['events']), 3)
        self.assertIsNone(logs['next_events_cursor'])

    def test_stage_archive_failure_does_not_lose_rental_identity(self):
        history.begin(self.label)
        path = history.folder(self.label)
        private = self.root/'private'
        private.write_text('private data')
        (path/'stages.jsonl.gz').symlink_to(private)
        history.update(self.label, instance_id='42', phase='Booting rig')
        record = history.read(self.label)
        self.assertEqual(record['instance_id'], '42')
        self.assertFalse(record['events_complete'])
        self.assertEqual(private.read_text(), 'private data')
        self.assertIn('events_error', history.log_page(self.label))

    def test_log_pages_keep_every_message_and_resume_on_utf8_boundaries(self):
        history.begin(self.label)
        writer = history.LogWriter(self.label)
        messages = ['Starting rig', '✓ Restoring sauvegardes 日本語', '  game output', 'Rig shut down']
        for index, message in enumerate(messages): writer.append(message, 1700000000000+index)
        page = history.log_page(self.label, limit=2)
        self.assertEqual([item['message'] for item in page['entries']], messages[:2])
        self.assertTrue(page['logs_complete'])
        second = history.log_page(self.label, page['next_cursor'], limit=2)
        self.assertEqual([item['message'] for item in second['entries']], messages[2:])
        self.assertIsNone(second['next_cursor'])
        self.assertEqual(second['entries'][-1]['time'], 1700000000003)
        with self.assertRaises(ValueError): history.log_page(self.label, 1)
        with self.assertRaises(ValueError): history.log_page('../private', 0)

    def test_log_pages_bound_responses_without_truncating_saved_rows(self):
        history.begin(self.label)
        messages = ['x'*600000, 'y'*600000]
        writer = history.LogWriter(self.label)
        for message in messages: writer.append(message)
        first = history.log_page(self.label)
        self.assertEqual(len(first['entries']), 1)
        second = history.log_page(self.label, first['next_cursor'])
        self.assertEqual(second['entries'][0]['message'], messages[1])
        self.assertIsNone(second['next_cursor'])
        target = history.folder(self.label)/'logs.jsonl.gz'
        target.unlink()
        with gzip.open(target, 'wt') as output:
            output.write(json.dumps(dict(time=None, message='Historical output'))+'\n')
        self.assertIsNone(history.log_page(self.label)['entries'][0]['time'])
        target.unlink(); target.symlink_to(self.root/'private')
        with self.assertRaises(ValueError): history.log_page(self.label)

    def test_session_reads_and_locks_reject_symlink_files(self):
        history.begin(self.label)
        path = history.folder(self.label)
        private = self.root/'private'
        private.write_text('private data')
        for name, operation in [('session.json', lambda: history.read(self.label)),
                                ('session.lock', lambda: history.log_page(self.label))]:
            original = (path/name).read_bytes()
            (path/name).unlink(); (path/name).symlink_to(private)
            with self.assertRaises(OSError): operation()
            self.assertEqual(private.read_text(), 'private data')
            (path/name).unlink(); (path/name).write_bytes(original)

    def test_exact_identity_survives_stop_and_late_updates(self):
        history.begin(self.label, 'fixture', 1700000000000, 'a'*32)
        history.update(self.label, creation_requested_at=1700000000100)
        history.attach(dict(id=42, label=self.label, gpu_name='RTX 3090', start_date=1700000000, dph_total=0.2))
        with self.assertRaises(ValueError): history.attach(dict(id=99, label=self.label))
        history.destroyed('99')
        self.assertIsNone(history.read(self.label)['ended_at'])
        history.destroyed('42')
        stopped = history.read(self.label)
        history.update(self.label, outcome='active', ended_at=None, phase='Starting game')
        self.assertEqual(history.read(self.label)['ended_at'], stopped['ended_at'])
        self.assertEqual(history.read(self.label)['outcome'], 'stopped')
        self.assertEqual(history.read(self.label)['instance_id'], '42')
        self.worker.assert_called_once_with(self.label)
        history.destroyed('42')
        self.worker.assert_called_once()

    def test_only_empty_closed_legacy_entries_are_hidden(self):
        empty = dict(recovered=True, outcome='stopped', rig={}, billing=dict(status='pending'))
        self.assertFalse(history.visible_session(empty))
        for fields in (dict(recovered=False), dict(outcome='unresolved'), dict(outcome='retained'),
                       dict(instance_id='42'), dict(rig=dict(gpu_name='RTX 3090')),
                       dict(hourly_price_usd='0.2'), dict(game_duration_ms=0),
                       dict(billing=dict(reported_usd='0'))):
            self.assertTrue(history.visible_session(dict(empty, **fields)))

    def test_starting_is_distinct_from_failure_before_and_after_instance_creation(self):
        for outcome in ('preparing', 'creating'):
            self.assertEqual(history.display_state(dict(outcome=outcome)), 'Starting')
        pending = dict(outcome='active', instance_id='42', operation_pending=True, last_attempt_success=False)
        self.assertEqual(history.display_state(pending), 'Starting')
        self.assertEqual(history.display_state(dict(pending, operation_pending=False)), 'Failed')
        self.assertEqual(history.display_state(dict(pending, ended_at=1, outcome='stopped')), 'Failed')
        self.assertEqual(history.display_state(dict(outcome='active', operation_pending=False, game_running=True)), 'Running')

    def test_filters_sort_the_whole_history_and_put_unknown_values_last(self):
        now = 1700000000000
        records = [dict(schema=1, id='vastgame-'+str(index), started_at=now-days*86400000,
                        outcome='stopped', ended_at=now, game_duration_ms=played,
                        billing=dict(status='reported', reported_usd=cost) if cost is not None else {})
                   for index, days, cost, played in [(1, 1, '2', 3000), (2, 2, '10', 1000), (3, 8, None, None)]]
        with patch.object(history, 'milliseconds', return_value=now):
            self.assertEqual([item['id'] for item in history.select_sessions(records, 3)], ['vastgame-1', 'vastgame-2'])
            self.assertEqual(history.select_sessions(records, state='Running'), [])
            self.assertEqual([item['id'] for item in history.select_sessions(records, order='highest-cost')], ['vastgame-2', 'vastgame-1', 'vastgame-3'])
            self.assertEqual([item['id'] for item in history.select_sessions(records, order='lowest-cost')], ['vastgame-1', 'vastgame-2', 'vastgame-3'])
            self.assertEqual([item['id'] for item in history.select_sessions(records, order='longest-time')], ['vastgame-1', 'vastgame-2', 'vastgame-3'])

    def test_observed_play_time_pauses_and_does_not_include_backup(self):
        history.begin(self.label)
        with patch.object(history, 'milliseconds', return_value=1000): history.update(self.label, game_running=True)
        with patch.object(history, 'milliseconds', return_value=6000):
            self.assertEqual(history.summary(history.read(self.label))['played_ms'], 5000)
            history.update(self.label, game_running=False)
        with patch.object(history, 'milliseconds', return_value=10000): history.update(self.label, game_running=True)
        with patch.object(history, 'milliseconds', return_value=12000): history.update(self.label, game_running=False)
        history.update(self.label, ended_at=20000, outcome='stopped')
        self.assertEqual(history.summary(history.read(self.label))['played_ms'], 7000)
        history.update(self.label, game_running=True)
        self.assertIsNone(history.read(self.label)['game_active_since'])

    def test_page_billing_fetches_once_and_matches_each_exact_instance(self):
        labels = [self.label, 'vastgame-1700000000000000001']
        for label, instance in zip(labels, ['42', '99']):
            history.begin(label, started_at=1700000000000)
            history.update(label, instance_id=instance)
        with patch.dict(sys.modules, charges=charges), patch.object(charges, 'fetch_charges', return_value=[]) as fetch:
            result = history.refresh_page([history.read(label) for label in labels])
        fetch.assert_called_once()
        self.assertEqual([record['instance_id'] for record in result], ['42', '99'])
        self.assertTrue(all(record['billing']['status'] == 'pending' for record in result))

    def test_failed_start_and_reconnect_keep_a_retained_session_open(self):
        history.begin(self.label, 'fixture', 1700000000000)
        history.update(self.label, creation_requested_at=1700000000100)
        history.attach(dict(id=42, label=self.label))
        history.finish_attempt(self.label, 1)
        history.job_update(dict(label=self.label, game='fixture', instance_id='42', finished=True, success=False))
        self.assertEqual(history.read(self.label)['outcome'], 'retained')
        self.assertIsNone(history.read(self.label)['ended_at'])
        history.job_update(dict(label=self.label, game='fixture', instance_id='42', finished=True, success=True))
        self.assertEqual(history.read(self.label)['started_at'], 1700000000000)
        self.assertIsNone(history.read(self.label)['ended_at'])
        self.worker.assert_not_called()

    def test_failed_rental_stays_failed_after_reconnect_shutdown_and_late_updates(self):
        history.begin(self.label, 'fixture')
        history.attach(dict(id=42, label=self.label))
        history.finish_attempt(self.label, 1)
        history.job_update(dict(label=self.label, instance_id='42', finished=True, success=True))
        history.destroyed('42')
        history.job_update(dict(label=self.label, finished=True, stopped=True, success=True))
        history.update(self.label, last_attempt_success=True, outcome='active', ended_at=None)
        record = history.read(self.label)
        self.assertTrue(record['failed'])
        self.assertEqual(record['outcome'], 'stopped')
        self.assertIsNotNone(record['ended_at'])
        self.assertEqual(history.summary(record)['state'], 'Failed')
        self.assertEqual(len(history.select_sessions([record], state='Failed')), 1)
        self.assertEqual(history.select_sessions([record], state='Shutdown'), [])

    def test_successful_and_canceled_rentals_do_not_become_failed(self):
        for forced in (False, True):
            label = history.new_label()
            history.begin(label, 'fixture'); history.attach(dict(id=42, label=label))
            if forced:
                history.update(label, force_shutdown=True, backup='forced_skip')
                history.job_update(dict(label=label, instance_id='42', force_shutdown=True, finished=True, success=False))
            else: history.finish_attempt(label, 0)
            history.destroyed('42', label)
            self.assertEqual(history.summary(history.read(label))['state'], 'Shutdown')

    def test_force_shutdown_preserves_real_failure_and_legacy_failure_evidence(self):
        history.begin(self.label, 'fixture'); history.attach(dict(id=42, label=self.label))
        with history.locked(self.label) as path:
            legacy = history.read(self.label)
            legacy.update(last_attempt_success=False, outcome='retained')
            history.write(path/'session.json', legacy)
        history.update(self.label, force_shutdown=True, backup='forced_skip')
        history.destroyed('42', self.label)
        self.assertTrue(history.read(self.label)['failed'])
        self.assertEqual(history.summary(history.read(self.label))['state'], 'Failed')

    def test_unknown_creation_does_not_become_a_zero_cost_failed_attempt(self):
        history.begin(self.label)
        history.update(self.label, creation_requested_at=history.milliseconds())
        history.finish_attempt(self.label, 1)
        self.assertEqual(history.read(self.label)['outcome'], 'unresolved')
        self.assertIsNone(history.read(self.label)['ended_at'])
        self.assertIsNone(history.summary(history.read(self.label))['estimated_compute_storage_usd'])

    def test_backup_receipt_requires_the_exact_instance(self):
        history.begin(self.label)
        history.update(self.label, instance_id='42')
        with self.assertRaises(ValueError): history.backup_receipt(self.label, dict(schema=1, instance_id='99', snapshot='verified-hash'))
        history.backup_receipt(self.label, dict(schema=1, instance_id='42', snapshot='verified-hash'))
        self.assertEqual(history.read(self.label)['backup'], 'verified')
        self.assertEqual(history.read(self.label)['backup_snapshot'], 'verified-hash')

    def test_force_shutdown_cannot_be_overwritten_by_a_late_backup_or_startup(self):
        history.begin(self.label)
        history.update(self.label, force_shutdown=True, backup='forced_skip', phase='Shutting down rig')
        history.attach(dict(id=42, label=self.label))
        history.update(self.label, phase='Game running', outcome='active', backup='verified', force_shutdown=False)
        record = history.read(self.label)
        self.assertTrue(record['force_shutdown'])
        self.assertEqual(record['backup'], 'forced_skip')
        self.assertEqual(record['phase'], 'Shutting down rig')
        self.assertEqual(record['instance_id'], '42')
        history.destroyed('42')
        self.assertEqual(history.read(self.label)['outcome'], 'stopped')

    def test_compressed_logs_keep_full_messages_without_credentials(self):
        history.begin(self.label)
        writer = history.LogWriter(self.label)
        writer.append('ERROR: token=private https://example.com/?secret=value')
        writer.append('-----BEGIN RSA PRIVATE KEY-----')
        writer.append('private-key-body')
        writer.append('-----END RSA PRIVATE KEY-----')
        writer.append('x'*12000)
        path = self.root/self.label/'logs.jsonl.gz'
        with gzip.open(path, 'rt') as incoming: logs = [json.loads(line) for line in incoming]
        self.assertNotIn('private-key-body', str(logs))
        self.assertNotIn('token=private', str(logs))
        self.assertNotIn('?secret=', str(logs))
        self.assertEqual(logs[-1]['message'], 'x'*12000)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_legacy_logs_are_imported_once_and_survive_job_removal(self):
        job = self.root.parent/'desktop'/('a'*32)
        job.mkdir(parents=True)
        (job/'job.json').write_text(json.dumps(dict(job='a'*32, label=self.label, game='fixture', stopped=True)))
        (job/'previous.jsonl').write_text(json.dumps(dict(type='log', time=1, line='Earlier output'))+'\n')
        (job/'events.jsonl').write_text(json.dumps(dict(type='log', time=2, line='Last output'))+'\n')
        history.archive_job(job/'job.json'); history.archive_job(job/'job.json')
        (job/'events.jsonl').unlink(); (job/'previous.jsonl').unlink(); (job/'job.json').unlink(); job.rmdir()
        with gzip.open(self.root/self.label/'logs.jsonl.gz', 'rt') as incoming:
            self.assertEqual([json.loads(line)['message'] for line in incoming], ['Earlier output', 'Last output'])
        record = history.read(self.label)
        self.assertFalse(record['logs_complete'])
        self.assertIsNone(history.summary(record)['duration_ms'])
        self.worker.assert_not_called()

    def test_refresh_errors_preserve_reported_cost_and_do_not_change_lifecycle(self):
        history.begin(self.label)
        history.update(self.label, instance_id='42', billing=dict(status='reported', reported_usd='0.123'))
        with patch.dict(sys.modules, charges=charges), patch.object(charges, 'fetch_charges', side_effect=ValueError('API unavailable')):
            result = history.refresh(self.label)
        self.assertEqual(result['billing']['reported_usd'], '0.123')
        self.assertEqual(result['billing']['status'], 'stale')
        self.assertEqual(result['instance_id'], '42')
        self.assertIsNone(result['ended_at'])
        with patch.dict(sys.modules, charges=charges), patch.object(charges, 'fetch_charges', return_value=[]):
            result = history.refresh(self.label)
        self.assertEqual(result['billing']['reported_usd'], '0.123')
        self.assertEqual(result['billing']['status'], 'stale')


class ChargeTests(unittest.TestCase):
    def row(self, amount='0.3', source='instance-42', start=1700000000, end=1700003600):
        return dict(type='instance', source=source, start=start, end=end, amount=amount,
                    metadata=dict(label='vastgame-123'), items=[dict(type='gpu', amount='0.2'), dict(type='storage', amount='0.1')])

    def test_exact_id_decimal_totals_and_idempotent_duplicate_pages(self):
        row = self.row()
        result = charges.session_charges([self.row(source='instance-99'), row, row], '42', 'vastgame-123')
        self.assertEqual(result['reported_usd'], '0.3')
        self.assertEqual(result['breakdown_usd'], dict(gpu='0.2', storage='0.1'))
        self.assertTrue(result['breakdown_complete'])
        self.assertFalse(result['final'])

    def test_missing_rows_label_mismatch_and_ambiguous_totals_never_claim_zero(self):
        self.assertEqual(charges.session_charges([], '42', 'vastgame-123')['status'], 'pending')
        with self.assertRaises(ValueError): charges.session_charges([self.row()], '42', 'vastgame-999')
        with self.assertRaises(ValueError): charges.session_charges([self.row(), self.row(amount='0.4')], '42', 'vastgame-123')
        with self.assertRaises(ValueError): charges.session_charges([self.row(amount='nan')], '42', 'vastgame-123')

    def test_bounded_pagination_uses_public_host_and_requires_every_page(self):
        import io
        first = dict(success=True, count=1, total=2, next_token='next', results=[self.row()])
        second = dict(success=True, count=1, total=2, next_token=None,
                      results=[self.row(start=1700003600, end=1700007200)])
        responses = [io.BytesIO(json.dumps(page).encode()) for page in (first, second)]
        with patch.object(charges, 'api_key', return_value='private-key'), patch.object(charges.urllib.request, 'build_opener') as opener:
            opener.return_value.open.side_effect = responses
            rows = charges.fetch_charges(1700000000, 1700007200)
        self.assertEqual(len(rows), 2)
        requests = [call.args[0] for call in opener.return_value.open.call_args_list]
        self.assertTrue(all(request.full_url.startswith('https://console.vast.ai/api/v0/charges/') for request in requests))
        self.assertTrue(all('private-key' not in request.full_url for request in requests))
        self.assertIn('after_token=next', requests[-1].full_url)
        broken = io.BytesIO(json.dumps(dict(success=True, count=0, total=2, next_token=None, results=[])).encode())
        with patch.object(charges, 'api_key', return_value='private-key'), patch.object(charges.urllib.request, 'build_opener') as opener:
            opener.return_value.open.return_value = broken
            with self.assertRaisesRegex(ValueError, 'incomplete'): charges.fetch_charges(1700000000, 1700007200)


class CaptureTests(unittest.TestCase):
    def test_cli_capture_preserves_terminal_detection_input_and_redirected_output(self):
        for terminal in (False, True):
            with self.subTest(terminal=terminal), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                fake = root/'engine'
                fake.write_text('#!/usr/bin/python3\nimport os\nprint("TTY="+str(os.isatty(1)), flush=True)\n'
                                'print("Choice="+input("Choose: "), flush=True)\nprint("token=private", flush=True)\n')
                fake.chmod(0o700)
                code = 'import sys; sys.path.insert(0, '+repr(str(PROJECT/'src/client'))+'); import session_capture as c; c.BIN=c.Path('+repr(str(fake))+'); sys.exit(c.run(["start","fixture"]))'
                master = slave = None
                if terminal: master, slave = pty.openpty()
                process = subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE,
                                           stdout=slave if terminal else subprocess.PIPE, stderr=subprocess.PIPE,
                                           env=dict(os.environ, XDG_STATE_HOME=str(root/'state'), XDG_CONFIG_HOME=str(root/'config')))
                if slave is not None: os.close(slave)
                try:
                    output, errors = process.communicate(b'fixture\n', timeout=5)
                    if master is not None:
                        blocks = []
                        while True:
                            try: block = os.read(master, 8192)
                            except OSError as exc:
                                if exc.errno == errno.EIO: break
                                raise
                            if not block: break
                            blocks.append(block)
                        output = b''.join(blocks)
                    self.assertEqual(process.returncode, 0, errors)
                    self.assertIn(('TTY='+str(terminal)).encode(), output)
                    self.assertIn(b'Choice=fixture', output)
                    self.assertIn(b'token=private', output)
                    logs = list((root/'state/vastgame/sessions').glob('vastgame-*/logs.jsonl.gz'))
                    self.assertEqual(len(logs), 1)
                    with gzip.open(logs[0], 'rt') as incoming: recorded = incoming.read()
                    self.assertIn('Choice=fixture', recorded)
                    self.assertNotIn('token=private', recorded)
                finally:
                    if process.poll() is None: process.kill(); process.wait()
                    if master is not None: os.close(master)


if __name__ == '__main__': unittest.main()
