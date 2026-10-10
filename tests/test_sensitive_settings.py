"""Sensitive actions use temporary archives and mocked provider/lifecycle calls."""
from contextlib import nullcontext
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/client'))
import sensitive_settings as sensitive
import session_history as history


class SensitiveSettingsTests(unittest.TestCase):
    def test_provider_targets_exclude_other_apps_and_reject_ambiguous_ids(self):
        self.assertEqual(sensitive.targets([{'id': 42, 'label': 'vastgame-123'},
            {'id': 43, 'label': 'training'}, {'id': 44, 'label': 'vastgame-other'}]), [('42', 'vastgame-123')])
        with self.assertRaises(ValueError): sensitive.targets([{'id': 42, 'label': 'vastgame-123'}, {'id': 42, 'label': 'vastgame-456'}])
        with self.assertRaises(ValueError): sensitive.targets([{'id': '42;bad', 'label': 'vastgame-123'}])

    def test_force_shutdown_continues_after_a_failure_and_only_confirms_successes(self):
        with patch.object(sensitive, 'jobs', return_value=[]), patch.object(sensitive, 'action_lock', return_value=nullcontext()), \
             patch.object(sensitive.desktop, 'instance_rows', return_value=[{'id': 42, 'label': 'vastgame-123'}, {'id': 43, 'label': 'vastgame-456'}]), \
             patch.object(sensitive, 'stop_instance', side_effect=[False, True]) as stop, patch.object(sensitive.desktop, 'emit'):
            result = sensitive.force_stop_all()
            self.assertFalse(result['ok'])
            self.assertEqual(result['confirmed'], ['43'])
            self.assertEqual(result['failed'][0]['id'], '42')
            self.assertEqual(stop.call_count, 2)

    def test_lookup_failure_never_submits_destroy(self):
        with patch.object(sensitive, 'jobs', return_value=[]), patch.object(sensitive, 'action_lock', return_value=nullcontext()), \
             patch.object(sensitive.desktop, 'instance_rows', side_effect=ValueError('Provider timeout')), \
             patch.object(sensitive, 'stop_instance') as stop:
            with self.assertRaises(ValueError): sensitive.force_stop_all()
            stop.assert_not_called()

    def test_deletion_erases_logs_and_summary_without_resurrection_or_control_loss(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(history, 'ROOT', Path(tmp)/'sessions'), \
             patch.object(sensitive, 'jobs', return_value=[]), patch.object(history, 'queue_refresh'):
            label = 'vastgame-123'
            history.begin(label, 'game')
            history.update(label, instance_id='42', rig={'gpu_name': 'RTX 4090'}, phase='Game running')
            history.LogWriter(label).append('Private session log')
            result = sensitive.delete_history()
            self.assertTrue(result['ok'])
            record = history.read(label)
            self.assertTrue(record['history_deleted'])
            self.assertEqual(record['instance_id'], '42')
            self.assertNotIn('rig', record)
            self.assertFalse(history.visible_session(record))
            history.LogWriter(label).append('Late worker output')
            history.update(label, phase='Game running', billing={'reported_usd': 1})
            self.assertFalse((history.folder(label)/'logs.jsonl.gz').exists())
            self.assertFalse((history.folder(label)/'stages.jsonl.gz').exists())
            self.assertNotIn('billing', history.read(label))
            with self.assertRaises(ValueError): history.log_page(label)
            history.update(label, outcome='stopped')
            self.assertTrue(history.read(label)['history_deleted'])
            history.update(label, outcome='active', instance_id='42')
            self.assertEqual(history.read(label)['outcome'], 'stopped')

    def test_legacy_import_does_not_recreate_deleted_history(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(history, 'ROOT', Path(tmp)/'sessions'):
            folder = Path(tmp)/'jobs'/('a'*32); folder.mkdir(parents=True)
            job = folder/'job.json'; job.write_text(json.dumps({'label': 'vastgame-456', 'job': 'a'*32, 'stopped': True}))
            with patch.object(sensitive, 'jobs', return_value=[{'label': 'vastgame-456'}]): sensitive.delete_history()
            history.archive_job(job)
            self.assertTrue(history.read('vastgame-456')['history_deleted'])
            self.assertFalse((history.folder('vastgame-456')/'logs.jsonl.gz').exists())
