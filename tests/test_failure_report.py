import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('failure_report', ROOT/'src/client/failure_report.py')
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class FailureReportTests(unittest.TestCase):
    def test_redaction_preserves_json_and_removes_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'report.json'
            report.json_write(path, dict(token='private', reason="instance_api_key: 'private'",
                                         source='https://example.test/download/private?sig=private',
                                         auth='Bearer private', tailscale='tskey-auth-private'))
            value = json.loads(path.read_text())
            self.assertEqual(value['token'], '[redacted]')
            self.assertNotIn('private', path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_events_keep_exact_identity_and_only_log_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/'reports'/'123'
            info = dict(id=123, label='vastgame-123', actual_status='created', instance_api_key='private')
            report.event(folder, info, 'game')
            report.event(folder, info, 'game')
            info['actual_status'] = 'running'
            report.event(folder, info, 'game')
            lines = (folder/'timeline.jsonl').read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])['instance']['id'], 123)
            self.assertNotIn('instance_api_key', '\n'.join(lines))

    def test_gpu_evidence_does_not_invent_underlying_cause(self):
        value = report.diagnose('Vast stopped', 'Error: GPU error, unable to start instance.', '')
        self.assertEqual(value['category'], 'provider_gpu')
        self.assertIn('not exposed', value['cause'])

    def test_missing_domain_is_explicitly_a_symptom(self):
        value = report.diagnose('timeout', "Domain not found: no domain with matching name 'C.123'", '')
        self.assertEqual(value['category'], 'provider_domain')
        self.assertIn('unknown', value['cause'])

    def test_history_counts_instance_once_and_never_penalizes_app_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            info = dict(id=123, machine_id=5, label='vastgame-123', image='image')
            for _ in range(2): report.record_failure(state, info, dict(category='provider_gpu'))
            report.record_failure(state, dict(info, id=124), dict(category='guest_permissions'))
            history = report.read(state/'host_history.json')['machine:5']
            self.assertEqual(len(history['provisioning_failures']), 1)

    def test_late_boot_clears_only_this_instances_penalty(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            info = dict(id=123, machine_id=5, label='vastgame-123', image='image')
            report.record_failure(state, info, dict(category='provider_gpu'))
            report.record_failure(state, dict(info, id=124), dict(category='provider_gpu'))
            report.event(state/'reports'/'123', dict(info, actual_status='running'), 'game')
            failures = report.read(state/'host_history.json')['machine:5']['provisioning_failures']
            self.assertEqual([entry['instance'] for entry in failures], ['124'])

    def test_local_timeout_is_pending_and_never_penalizes_host(self):
        value = report.diagnose('Boot wait paused: Vast did not reach running within 15m 00s.',
                                "Domain not found: no domain with matching name 'C.123'", '')
        self.assertEqual(value['category'], 'waiting')
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            report.record_failure(state, dict(id=123, machine_id=5, label='vastgame-123'), value)
            self.assertFalse((state/'host_history.json').exists())

    def test_explicit_current_gpu_error_survives_timeout_summary(self):
        value = report.diagnose('Boot wait paused: deadline', '', '',
            dict(actual_status='created', intended_status='stopped',
                 status_msg='Error: GPU error, unable to start instance.'))
        self.assertEqual(value['category'], 'provider_gpu')

    def test_running_guest_ignores_historical_provider_errors(self):
        value = report.diagnose('Client failed', 'GPU error, unable to start instance',
                               'symbol lookup error: Qt', dict(actual_status='running'))
        self.assertEqual(value['category'], 'client_libraries')
